"""Resolution boundaries, inheritance invariants, immutable results, and lock replay."""

import builtins
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from typing import Any, cast

import pytest
from pydantic import ValidationError
from reliclab.resolve import CompositionLock, LockedModule, ResolutionError, engine, resolve, types
from reliclab.schema import Composition, ModuleKey, Persona, RelicError
from reliclab.vault import CatalogSnapshot

from tests.support.resolve import catalog, composition, snapshot
from tests.support.vault import asset


def test_merge_is_parent_first_without_erasing_constraints() -> None:
    parent = asset(
        id="parent",
        identity="Parent",
        voice="Formal",
        body="Parent body.\n",
        values=["A", "B"],
        constraints=["Keep", "Keep"],
    )
    child = asset(
        id="child",
        identity="Child",
        voice="",
        extends="parent@1",
        body="Child body.\n",
        values=["B", "C"],
        constraints=[],
    )
    graph = resolve(composition(persona="child"), catalog(child, parent))
    assert [item.key.id for item in graph.persona_chain] == ["parent", "child"]
    assert graph.persona is not None
    assert graph.persona.identity == "Child"
    assert graph.persona.voice == ""
    assert graph.persona.values == ("A", "B", "C")
    assert graph.persona.constraints == ("Keep",)
    assert [section.text for section in graph.persona.sections] == [
        "Parent body.\n",
        "Child body.\n",
    ]
    assert (
        graph.persona.body
        == "## Persona parent@1.0.0\n\nParent body.\n\n\n## Persona child@1.0.0\n\nChild body.\n"
    )
    assert graph.lock.modules[0].key == parent.key
    assert isinstance(parent, Persona)
    assert parent.constraints == ("Keep", "Keep")


def test_three_levels_exact_deduplication_and_metadata_remain_local() -> None:
    source = catalog(
        asset(
            id="base",
            values=["A"],
            constraints=["Rule"],
            tags=["parent"],
            extensions={"x-parent": True},
        ),
        asset(id="middle", extends="base", values=["a", "B"], constraints=["Rule", "rule"]),
        asset(id="leaf", extends="middle", values=["A", "C"], constraints=["Last"], tags=["child"]),
    )
    graph = resolve(composition(persona="leaf"), source)
    assert graph.persona is not None
    assert graph.persona.values == ("A", "a", "B", "C")
    assert graph.persona.constraints == ("Rule", "rule", "Last")
    assert graph.persona.body == ""
    assert graph.persona_chain[-1].document.tags == ("child",)
    assert graph.persona_chain[-1].document.extensions == {}


@pytest.mark.parametrize(
    "slots",
    [
        {"persona": "sample"},
        {"skills": ["sample"]},
        {"memory": ["sample"]},
        {"persona": "sample", "skills": ["sample"], "memory": ["sample"]},
    ],
)
def test_four_composition_modes_and_typed_identity(slots: dict[str, Any]) -> None:
    source = catalog(asset(), asset("skill"), asset("memory"))
    request = composition(**slots)
    graph = resolve(request, source)
    assert len(graph.modules) == len(slots)
    assert (graph.persona is not None) == ("persona" in slots)
    assert graph.composition == request


def test_declaration_order_is_not_catalog_order() -> None:
    source = catalog(
        asset("skill", id="a"),
        asset("skill", id="b"),
        asset("memory", id="a"),
        asset("memory", id="b"),
        asset(),
    )
    graph = resolve(composition(persona="sample", skills=["b", "a"], memory=["b", "a"]), source)
    assert [(item.key.kind, item.key.id) for item in graph.modules] == [
        ("persona", "sample"),
        ("skill", "b"),
        ("skill", "a"),
        ("memory", "b"),
        ("memory", "a"),
    ]


@pytest.mark.parametrize("cycle", [1, 2, 3])
def test_cycles_include_entire_reference_chain(cycle: int) -> None:
    source = catalog(
        *(asset(id=f"p{index}", extends=f"p{(index + 1) % cycle}") for index in range(cycle))
    )
    with pytest.raises(ResolutionError) as caught:
        resolve(composition(persona="p0"), source)
    assert caught.value.code == "DEPENDENCY_CYCLE"
    assert caught.value.chain == ("composition:workflow@1.0.0",) + tuple(
        f"persona:p{index}" for index in range(cycle)
    ) + ("persona:p0",)
    assert tuple(item.source for item in caught.value.details) == caught.value.chain


def test_same_persona_id_at_different_versions_is_conflict() -> None:
    source = catalog(asset(version="1.0.0"), asset(version="2.0.0", extends="sample@1.0.0"))
    with pytest.raises(ResolutionError) as caught:
        resolve(composition(persona="sample@2.0.0"), source)
    assert caught.value.code == "VERSION_CONFLICT"
    assert caught.value.chain[-1] == "persona:sample@1.0.0"


@pytest.mark.parametrize("depth", [31, 32, 33])
def test_inheritance_depth_boundary(depth: int) -> None:
    source = catalog(
        *(
            asset(id=f"p{index}", extends=f"p{index + 1}" if index + 1 < depth else None)
            for index in range(depth)
        )
    )
    if depth <= 32:
        assert len(resolve(composition(persona="p0"), source).persona_chain) == depth
    else:
        with pytest.raises(ResolutionError) as caught:
            resolve(composition(persona="p0"), source)
        assert caught.value.code == "VERSION_CONFLICT"
        assert len(caught.value.chain) == 34


@pytest.mark.parametrize("kind", ["skill", "memory", "persona"])
def test_wrong_kind_is_never_inferred(kind: str) -> None:
    source = catalog(asset("composition"))
    slots = (
        {"persona": "sample"}
        if kind == "persona"
        else {"skills" if kind == "skill" else "memory": ["sample"]}
    )
    with pytest.raises(ResolutionError) as caught:
        resolve(composition(**slots), source)
    assert caught.value.code == "VERSION_CONFLICT"


def test_missing_parent_preserves_chain_without_content_leak() -> None:
    source = catalog(
        asset(id="child", extends="parent", body="fixture-secret-value"),
        asset(id="parent", extends="missing@1"),
    )
    with pytest.raises(ResolutionError) as caught:
        resolve(composition(persona="child"), source)
    assert caught.value.code == "NOT_FOUND"
    assert caught.value.chain == (
        "composition:workflow@1.0.0",
        "persona:child",
        "persona:parent",
        "persona:missing@1",
    )
    assert "fixture-secret-value" not in repr(caught.value.details)


@pytest.mark.parametrize(
    "reference",
    ["sample@latest", "sample@*", "sample@~1.0.0", "sample@>=1.0.0", "sample@01", "sample@1.2.*"],
)
def test_unvalidated_selectors_are_rejected(reference: str) -> None:
    request = composition(skills=["sample"])
    invalid = request.model_copy(
        update={"modules": request.modules.model_copy(update={"skills": (reference,)})}
    )
    with pytest.raises(RelicError) as caught:
        resolve(invalid, catalog(asset("skill")))
    assert caught.value.code == "SCHEMA_INVALID"


@pytest.mark.parametrize("references", [("sample", "sample"), ("sample@1", "sample@2")])
def test_duplicate_slot_ids_revalidated(references: tuple[str, ...]) -> None:
    request = composition(skills=["sample"])
    invalid = request.model_copy(
        update={"modules": request.modules.model_copy(update={"skills": references})}
    )
    with pytest.raises(RelicError) as caught:
        resolve(invalid, catalog(asset("skill")))
    assert caught.value.code == "SCHEMA_INVALID"


def test_noncomposition_rejected() -> None:
    with pytest.raises(RelicError) as caught:
        resolve(cast(Composition, asset()), catalog())
    assert caught.value.code == "SCHEMA_INVALID"


def test_very_long_partial_selector_is_not_integer_conversion_failure() -> None:
    with pytest.raises(ResolutionError) as caught:
        resolve(composition(skills=["sample@" + "9" * 5000]), catalog(asset("skill")))
    assert caught.value.code == "NOT_FOUND"


def test_merged_body_limit_counts_section_headers_and_utf8() -> None:
    source = catalog(asset(body="\u4e2d\u6587\n"))
    request = composition(persona="sample")
    graph = resolve(request, source)
    assert graph.persona is not None
    size = len(graph.persona.body.encode("utf-8"))
    assert resolve(request, source, max_body_bytes=size).persona == graph.persona
    with pytest.raises(ResolutionError) as caught:
        resolve(request, source, max_body_bytes=size - 1)
    assert caught.value.code == "CONTEXT_OVERFLOW"


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_host_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        resolve(composition(skills=["sample"]), catalog(asset("skill")), max_body_bytes=limit)


def test_lock_prevents_implicit_upgrades_and_explicit_refresh_changes_digest() -> None:
    request = composition(skills=["sample"])
    original = resolve(request, catalog(asset("skill")))
    expanded = catalog(asset("skill"), asset("skill", version="2.0.0"))
    assert resolve(request, expanded, lock=original.lock) == original
    assert resolve(request, expanded).skills[0].key.version == "2.0.0"
    assert resolve(request, expanded).lock.digest != original.lock.digest


@pytest.mark.parametrize(
    "change", ["missing", "changed", "same-precedence", "missing-entry", "wrong-selector"]
)
def test_lock_never_falls_back(change: str) -> None:
    request = composition(skills=["sample@1"])
    original = resolve(request, catalog(asset("skill")))
    lock = original.lock
    if change == "missing":
        source = catalog(asset("skill", version="1.1.0"))
    elif change == "changed":
        source = catalog(asset("skill", body="Changed bytes"))
    elif change == "same-precedence":
        source = catalog(asset("skill", version="1.0.0+build"))
    elif change == "missing-entry":
        source = catalog(asset("skill"))
        lock = lock.model_copy(update={"modules": ()})
    else:
        source = catalog(asset("skill", version="2.0.0"))
        lock = lock.model_copy(
            update={
                "modules": (
                    LockedModule(
                        key=source.modules[0].key, content_hash=source.modules[0].content_hash
                    ),
                )
            }
        )
    with pytest.raises(ResolutionError) as caught:
        resolve(request, source, lock=lock)
    assert caught.value.code == "SOURCE_CHANGED"
    assert caught.value.chain[-1] == "skill:sample@1"


@pytest.mark.parametrize("change", ["variables", "body", "render", "selection", "name"])
def test_composition_changes_invalidate_lock(change: str) -> None:
    request = composition(skills=["sample"])
    source = catalog(asset("skill"))
    lock = resolve(request, source).lock
    changes: dict[str, Any] = {
        "variables": {"flag": True},
        "body": "note",
        "render": request.render.model_copy(update={"token_budget": 30}),
        "selection": request.modules.model_copy(update={"skills": ("sample@1",)}),
        "name": "Changed",
    }
    changed = request.model_copy(
        update={"modules" if change == "selection" else change: changes[change]}
    )
    with pytest.raises(ResolutionError) as caught:
        resolve(changed, source, lock=lock)
    assert caught.value.code == "SOURCE_CHANGED"
    assert caught.value.chain == ("composition:workflow@1.0.0",)


@pytest.mark.parametrize("change", ["extra", "reordered"])
def test_lock_requires_exact_ordered_dependency_closure(change: str) -> None:
    request = composition(skills=["a", "b"])
    source = catalog(asset("skill", id="a"), asset("skill", id="b"), asset("memory"))
    lock = resolve(request, source).lock
    entries = (
        tuple(reversed(lock.modules))
        if change == "reordered"
        else lock.modules
        + (LockedModule(key=source.modules[0].key, content_hash=source.modules[0].content_hash),)
    )
    with pytest.raises(ResolutionError) as caught:
        resolve(request, source, lock=lock.model_copy(update={"modules": entries}))
    assert caught.value.code == "SOURCE_CHANGED"


def test_lock_schema_revalidated_before_replay() -> None:
    source = catalog(asset("skill"))
    request = composition(skills=["sample"])
    lock = resolve(request, source).lock.model_copy(update={"resolver_version": "2.0"})
    with pytest.raises(ResolutionError) as caught:
        resolve(request, source, lock=lock)
    assert caught.value.code == "SCHEMA_INVALID"


def test_graph_is_immutable_and_has_detached_composition_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = composition(skills=["sample"]).model_copy(update={"variables": {"x": "before"}})
    source = catalog(asset("skill", extensions={"x-nested": {"value": "before"}}))
    monkeypatch.setattr(builtins, "open", lambda *a, **k: pytest.fail("Resolver performed I/O"))
    graph = resolve(request, source)
    request.variables["x"] = "after"
    graph.composition.variables["x"] = "after"
    graph.skills[0].document.extensions["x-nested"] = "after"
    assert graph.composition.variables == {"x": "before"}
    assert graph.skills[0].document.extensions == {"x-nested": {"value": "before"}}
    with pytest.raises(FrozenInstanceError):
        cast(Any, graph).skills = ()


def test_lock_json_canonical_roundtrip_and_digest() -> None:
    lock = resolve(composition(skills=["sample"]), catalog(asset("skill"))).lock
    text = lock.to_json()
    assert CompositionLock.from_json(text) == lock
    assert CompositionLock.from_json(text.encode()) == lock
    assert CompositionLock.from_json(json.dumps(json.loads(text), indent=4)).digest == lock.digest
    assert lock.digest == hashlib.sha256(text.encode()).hexdigest()
    assert "relative_path" not in text


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        "null",
        "{}",
        '{"lock_version":"1.0","lock_version":"1.0"}',
        b"\xff",
        "[" * 1100 + "]" * 1100,
        "\ud800",
    ],
)
def test_malformed_locks_are_value_free_domain_errors(text: str | bytes) -> None:
    with pytest.raises(RelicError) as caught:
        CompositionLock.from_json(text)
    assert caught.value.code == "SCHEMA_INVALID"


@pytest.mark.parametrize(
    "change",
    [
        {"lock_version": "2.0"},
        {"resolver_version": "2.0"},
        {"composition_hash": "A" * 64},
        {"extra": 1},
    ],
)
def test_unsupported_lock_fields(change: dict[str, object]) -> None:
    lock = resolve(composition(skills=["sample"]), catalog(asset("skill"))).lock
    data = lock.model_dump(mode="json") | change
    with pytest.raises(RelicError):
        CompositionLock.from_json(json.dumps(data))


@pytest.mark.parametrize("kind", ["duplicate", "composition"])
def test_invalid_lock_module_identities(kind: str) -> None:
    lock = resolve(composition(skills=["sample"]), catalog(asset("skill"))).lock
    entry = (
        lock.modules[0]
        if kind == "duplicate"
        else LockedModule(key=composition(skills=["sample"]).key, content_hash="0" * 64)
    )
    with pytest.raises(ValidationError):
        lock.model_copy(update={"modules": lock.modules + (entry,)}).to_json()


def test_lock_byte_limit_in_both_directions(monkeypatch: pytest.MonkeyPatch) -> None:
    lock = resolve(composition(skills=["sample"]), catalog(asset("skill"))).lock
    text = lock.to_json()
    monkeypatch.setattr(types, "MAX_LOCK_BYTES", len(text.encode()))
    assert CompositionLock.from_json(text).to_json() == text
    monkeypatch.setattr(types, "MAX_LOCK_BYTES", len(text.encode()) - 1)
    with pytest.raises(RelicError):
        CompositionLock.from_json(text)
    with pytest.raises(RelicError):
        lock.to_json()


def test_unrepresentable_canonical_data_is_domain_error() -> None:
    with pytest.raises(RelicError) as caught:
        types.canonical_json({"value": object()})
    assert caught.value.code == "SCHEMA_INVALID"


def test_catalog_revalidates_integrity_and_rejects_duplicate_keys() -> None:
    original = snapshot(asset())
    assert CatalogSnapshot((original,)).modules == (original,)
    with pytest.raises(RelicError) as caught:
        CatalogSnapshot((original, replace(original, relative_path="personas/another.md")))
    assert caught.value.code == "VERSION_CONFLICT"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"content": bytearray(b"invalid")}, "SCHEMA_INVALID"),
        (
            {"key": ModuleKey.model_construct(kind="invalid", id="sample", version="1.0.0")},
            "SCHEMA_INVALID",
        ),
        ({"relative_path": "../outside.md"}, "PATH_DENIED"),
        ({"relative_path": "personas/\ud800.md"}, "PATH_DENIED"),
        ({"relative_path": "skills/sample.md"}, "PATH_DENIED"),
        ({"relative_path": "personas/nested/sample.md"}, "PATH_DENIED"),
        ({"relative_path": "personas/sample.txt"}, "PATH_DENIED"),
        ({"relative_path": "personas/*.md"}, "PATH_DENIED"),
        ({"content_hash": "0" * 64}, "SOURCE_CHANGED"),
        ({"key": ModuleKey(kind="persona", id="another", version="1.0.0")}, "SOURCE_CHANGED"),
    ],
)
def test_catalog_does_not_trust_constructed_snapshots(change: dict[str, Any], code: str) -> None:
    with pytest.raises(RelicError) as caught:
        CatalogSnapshot((replace(snapshot(asset()), **change),))
    assert caught.value.code == code


def test_catalog_casefold_collision_across_distinct_keys() -> None:
    with pytest.raises(RelicError) as caught:
        CatalogSnapshot(
            (snapshot(asset(), "personas/one.md"), snapshot(asset(id="other"), "personas/ONE.md"))
        )
    assert caught.value.code == "VERSION_CONFLICT"


@pytest.mark.parametrize("inherited", [False, True])
def test_resolution_module_limit(inherited: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "MAX_RESOLVED_MODULES", 2)
    source = catalog(asset(id="parent"), asset(extends="parent"), asset("skill"), asset("memory"))
    request = composition(persona="sample", skills=["sample"])
    if not inherited:
        request = composition(persona="sample", skills=["sample"], memory=["sample"])
    with pytest.raises(ResolutionError) as caught:
        resolve(request, source)
    assert caught.value.code == "CONTEXT_OVERFLOW"
    assert len(caught.value.chain) == (3 if inherited else 1)


def test_inherited_parents_are_pinned_and_verified() -> None:
    request = composition(persona="child")
    child = asset(id="child", extends="parent")
    parent = asset(id="parent", constraints=["Keep this"])
    original = resolve(request, catalog(child, parent))
    newer = catalog(child, parent, asset(id="parent", version="2.0.0"))
    assert resolve(request, newer, lock=original.lock) == original
    with pytest.raises(ResolutionError) as caught:
        resolve(request, catalog(child, asset(id="parent", constraints=[])), lock=original.lock)
    assert caught.value.code == "SOURCE_CHANGED"
    assert caught.value.chain == ("composition:workflow@1.0.0", "persona:child", "persona:parent")


def test_external_memory_is_resolved_without_reading_its_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = catalog(asset("memory", source="file", root="notes", path="project.md", body=""))
    monkeypatch.setattr(builtins, "open", lambda *a, **k: pytest.fail("External note was read"))
    graph = resolve(composition(memory=["sample"]), source)
    assert graph.memory[0].document.body == ""


def test_generated_lock_must_fit_persistence_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(types, "MAX_LOCK_BYTES", 1)
    with pytest.raises(RelicError) as caught:
        resolve(composition(skills=["sample"]), catalog(asset("skill")))
    assert caught.value.code == "SCHEMA_INVALID"
