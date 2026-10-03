"""Composition ordering, provenance, trust, isolation, and input boundaries."""

import builtins
import hashlib
import json
import os
import time
from dataclasses import FrozenInstanceError, replace
from typing import Any, cast

import pytest
from pydantic import ValidationError
from reliclab.compose import ComposeLimits, ComposeRequest, compose
from reliclab.resolve import LockedModule, resolve
from reliclab.resolve.types import canonical_json
from reliclab.schema import RelicError

from tests.support.compose import golden_graph
from tests.support.resolve import catalog, composition
from tests.support.vault import asset


def test_order_provenance_inheritance_and_trust() -> None:
    graph = golden_graph("combined")
    trusted = tuple(item for item in graph.lock.modules if item.key.kind != "memory")
    result = compose(
        graph, ComposeRequest(variables={"project": "RelicLab"}, trusted_sources=trusted)
    )
    assert [block.source_key.id for block in result.blocks] == [
        "parent",
        "editor",
        "review",
        "notes",
    ]
    assert [block.order for block in result.blocks] == list(range(4))
    assert [block.trust for block in result.blocks] == ["instruction"] * 3 + ["reference"]
    assert all(block.required for block in result.blocks)
    assert "Unused parent" not in result.to_json()
    assert "Accuracy" in result.blocks[0].text
    assert "Accuracy" not in result.blocks[1].text
    assert "Review before executing." in result.blocks[1].text
    assert result.blocks[-1].text == "Literal {{ project }}.\n"
    for block, source in zip(result.blocks, graph.modules, strict=True):
        assert block.source_key == source.key
        assert block.source_hash == source.content_hash
        assert block.source_relative_path == source.relative_path
        assert block.block_id == f"{source.key.kind}:{source.key.id}@{source.key.version}"
    assert result.ir_version == "1.0"
    assert result.diagnostics == ()
    assert result.budget_report.status == "not_evaluated"
    assert result.budget_report.counter_id == "unmeasured"
    assert result.budget_report.token_budget == 8000
    assert result.tools[0].trust == "instruction"


def test_noop_ancestor_retained_in_manifest_and_leaf_empty_voice_does_not_inherit() -> None:
    graph = resolve(
        composition(persona="leaf"),
        catalog(asset(id="base", voice="Parent voice"), asset(id="leaf", extends="base")),
    )
    result = compose(graph)
    assert len(result.blocks) == 1
    assert result.blocks[0].text == "## Identity\n\nEditor"
    assert len(result.manifest.sources) == 2
    assert result.blocks[0].trust == "reference"


def test_skill_and_memory_follow_declaration_order() -> None:
    graph = resolve(
        composition(skills=["z", "a"], memory=["z", "a"]),
        catalog(
            asset("skill", id="a"),
            asset("skill", id="z"),
            asset("memory", id="a", scope="always"),
            asset("memory", id="z", scope="always"),
        ),
    )
    assert [(block.kind, block.source_key.id) for block in compose(graph).blocks] == [
        ("skill", "z"),
        ("skill", "a"),
        ("memory", "z"),
        ("memory", "a"),
    ]


def test_memory_selection_and_literal_templates() -> None:
    graph = resolve(
        composition(memory=["on-demand", "always"]),
        catalog(
            asset("memory", id="always", scope="always", body="{{ missing }}"),
            asset("memory", id="on-demand", body="{% include 'secret' %}"),
        ),
    )
    assert len(compose(graph).blocks) == 1
    result = compose(graph, ComposeRequest(selected_memory_ids=("always", "on-demand")))
    assert [block.required for block in result.blocks] == [False, True]
    assert all(block.trust == "reference" for block in result.blocks)
    assert result.manifest.selected_memory_ids == ("on-demand", "always")
    for selected in [("unknown",), ("always", "always")]:
        with pytest.raises(RelicError, match="Memory ID"):
            compose(graph, ComposeRequest(selected_memory_ids=selected))


@pytest.mark.parametrize("source", ["file", "glob"])
def test_external_memory_fails_explicitly_only_when_selected(source: str) -> None:
    graph = resolve(
        composition(memory=["sample"]),
        catalog(
            asset(
                "memory",
                source=source,
                root="notes",
                path="notes.md" if source == "file" else "*.md",
                body="",
            )
        ),
    )
    assert compose(graph).blocks == ()
    with pytest.raises(RelicError, match="captured-note") as failure:
        compose(graph, ComposeRequest(selected_memory_ids=("sample",)))
    assert failure.value.details[0].location == ("source",)
    assert failure.value.details[0].source == "memory/sample@1.0.0.md"


def test_host_variables_override_defaults_without_mutating_inputs() -> None:
    root = composition(persona="sample").model_copy(update={"variables": {"x": "default", "y": 4}})
    graph = resolve(root, catalog(asset(identity="{{ x }} {{ y }}")))
    request = ComposeRequest(variables={"x": "host"}, token_budget=123)
    result = compose(graph, request)
    assert result.blocks[0].text == "## Identity\n\nhost 4"
    assert root.variables == {"x": "default", "y": 4}
    assert request.variables == {"x": "host"}
    assert result.budget_report.token_budget == 123
    assert result.manifest.variables == {"x": "host", "y": 4}


@pytest.mark.parametrize(
    ("kind", "changes", "field"),
    [
        ("persona", {"identity": "{{ missing }}"}, "identity"),
        ("persona", {"voice": "{{ missing }}"}, "voice"),
        ("persona", {"values": ["{{ missing }}"]}, "values"),
        ("persona", {"constraints": ["{{ missing }}"]}, "constraints"),
        ("persona", {"body": "{{ missing }}"}, "body"),
        ("skill", {"body": "{{ missing }}"}, "body"),
        ("skill", {"trigger": "{{ missing }}"}, "trigger"),
        ("skill", {"examples": [{"input": "{{ missing }}", "output": "literal"}]}, "examples"),
        ("skill", {"examples": [{"input": "literal", "output": "{{ missing }}"}]}, "examples"),
    ],
)
def test_each_template_field_requires_explicit_variables(
    kind: str, changes: dict[str, Any], field: str
) -> None:
    root = composition(persona="sample") if kind == "persona" else composition(skills=["sample"])
    graph = resolve(root, catalog(asset(kind, **changes)))
    with pytest.raises(RelicError, match="missing") as failure:
        compose(graph)
    assert failure.value.details[0].location == (field,)
    result = compose(graph, ComposeRequest(variables={"missing": "Supplied"}))
    assert "Supplied" in result.blocks[0].text


def test_exact_block_byte_boundary_and_canonical_memory_selection() -> None:
    graph = resolve(
        composition(memory=["a", "b"]),
        catalog(asset("memory", id="a", body="\u4e2d\n"), asset("memory", id="b", body="\u6587\n")),
    )
    limits = ComposeLimits(max_block_bytes=4)
    first = compose(graph, ComposeRequest(selected_memory_ids=("a", "b")), limits=limits)
    second = compose(graph, ComposeRequest(selected_memory_ids=("b", "a")), limits=limits)
    assert first.to_json() == second.to_json()
    assert [block.text for block in first.blocks] == ["\u4e2d\n", "\u6587\n"]
    with pytest.raises(RelicError) as failure:
        compose(
            graph,
            ComposeRequest(selected_memory_ids=("a",)),
            limits=ComposeLimits(max_block_bytes=3),
        )
    assert failure.value.code == "CONTEXT_OVERFLOW"


@pytest.mark.parametrize("variables", [{"x": []}, {"x": {}}, {"x": float("inf")}, {"bad.name": 1}])
def test_invalid_or_mutated_variables_are_revalidated(variables: dict[str, Any]) -> None:
    graph = resolve(composition(persona="sample"), catalog(asset()))
    request = ComposeRequest()
    request.variables.update(variables)
    with pytest.raises(RelicError) as failure:
        compose(graph, request)
    assert failure.value.code == "SCHEMA_INVALID"


@pytest.mark.parametrize(
    "values",
    [
        {"token_budget": 0},
        {"token_budget": True},
        {"counter_id": "fake"},
        {"renderer_version": "1.0"},
        {"unknown": True},
        {"variables": {"a\n": "b"}},
    ],
)
def test_request_rejects_unsupported_fields(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ComposeRequest.model_validate(values)


def test_limits_and_invalid_utf8_variables() -> None:
    graph = resolve(composition(persona="sample"), catalog(asset(identity="{{ x }}")))
    for request, limits in [
        (ComposeRequest(variables={"x": "a", "y": "b"}), ComposeLimits(max_variables=1)),
        (ComposeRequest(variables={"x": "\u4e2d"}), ComposeLimits(max_variable_bytes=2)),
        (ComposeRequest(variables={"x": "xx"}), ComposeLimits(max_block_bytes=1)),
        (ComposeRequest(variables={"x": "xx"}), ComposeLimits(max_context_bytes=1)),
        (ComposeRequest(variables={"x": "xx"}), ComposeLimits(max_context_bytes=100)),
    ]:
        with pytest.raises(RelicError) as failure:
            compose(graph, request, limits=limits)
        assert failure.value.code == "CONTEXT_OVERFLOW"
    with pytest.raises(RelicError, match="UTF-8"):
        compose(graph, ComposeRequest(variables={"x": "\ud800"}))
    with pytest.raises(RelicError, match="Invalid"):
        compose(graph, limits=ComposeLimits.model_construct(max_block_bytes=0))


def test_memory_and_expanded_fields_respect_block_limits() -> None:
    graph = resolve(composition(memory=["sample"]), catalog(asset("memory", scope="always")))
    with pytest.raises(RelicError, match="blocks"):
        compose(graph, limits=ComposeLimits(max_block_bytes=1))
    graph = resolve(composition(persona="sample"), catalog(asset(values=["{{x}}", "{{ x }}"])))
    with pytest.raises(RelicError, match="block"):
        compose(
            graph,
            ComposeRequest(variables={"x": "a" * 40}),
            limits=ComposeLimits(max_block_bytes=60),
        )


@pytest.mark.parametrize("case", ["stale", "duplicate", "memory", "unknown"])
def test_trust_requires_exact_host_reviewed_instruction_source(case: str) -> None:
    graph = golden_graph("combined")
    record = graph.lock.modules[0]
    records = {
        "stale": (record.model_copy(update={"content_hash": "0" * 64}),),
        "duplicate": (record, record),
        "memory": (graph.lock.modules[-1],),
        "unknown": (LockedModule(key=asset(id="other").key, content_hash="0" * 64),),
    }
    with pytest.raises(RelicError) as failure:
        compose(graph, ComposeRequest(variables={"project": "X"}, trusted_sources=records[case]))
    assert failure.value.code == "SOURCE_CHANGED"


def test_forged_effective_persona_is_rejected() -> None:
    graph = golden_graph("persona")
    assert graph.persona is not None
    forged = replace(graph, persona=replace(graph.persona, identity="Injected"))
    with pytest.raises(RelicError) as failure:
        compose(forged)
    assert failure.value.code == "SOURCE_CHANGED"


def tool(name: str = "read", **changes: Any) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Read {{ literal }}",
        "input_schema": {"type": "object"},
        **changes,
    }


def test_identical_tools_merge_sources_in_order_and_require_unanimous_trust() -> None:
    graph = resolve(
        composition(skills=["z", "a"]),
        catalog(
            asset("skill", id="z", tools=[tool(), tool(), tool("write")]),
            asset("skill", id="a", tools=[tool()]),
        ),
    )
    result = compose(graph, ComposeRequest(trusted_sources=(graph.lock.modules[0],)))
    assert [item.requirement.name for item in result.tools] == ["read", "write"]
    assert [item.key.id for item in result.tools[0].sources] == ["z", "a"]
    assert [item.trust for item in result.tools] == ["reference", "instruction"]
    assert result.tools[0].requirement.description == "Read {{ literal }}"
    fully_trusted = compose(graph, ComposeRequest(trusted_sources=graph.lock.modules))
    assert all(item.trust == "instruction" for item in fully_trusted.tools)


@pytest.mark.parametrize(
    "changes",
    [
        {"description": "Different"},
        {"input_schema": {"type": "object", "additionalProperties": False}},
    ],
)
def test_conflicting_tools_report_both_sources(changes: dict[str, Any]) -> None:
    graph = resolve(
        composition(skills=["a", "b"]),
        catalog(
            asset("skill", id="a", tools=[tool()]), asset("skill", id="b", tools=[tool(**changes)])
        ),
    )
    with pytest.raises(RelicError) as failure:
        compose(graph)
    assert failure.value.code == "VERSION_CONFLICT"
    assert [item.source for item in failure.value.details] == [
        "skills/a@1.0.0.md",
        "skills/b@1.0.0.md",
    ]
    assert all(item.location == ("tools", "read") for item in failure.value.details)


def test_result_accessors_cannot_mutate_canonical_bytes_or_digest() -> None:
    graph = golden_graph("combined")
    request = ComposeRequest(variables={"project": "Original"})
    result = compose(graph, request)
    original = result.to_json()
    request.variables["project"] = "Changed"
    result.manifest.variables["project"] = "Changed"
    result.tools[0].requirement.input_schema["description"] = "Changed"
    assert result.to_json() == original
    with pytest.raises(FrozenInstanceError):
        cast(Any, result)._payload_json = "{}"
    payload = json.loads(original)
    digest = payload.pop("digest")
    assert digest == result.digest == hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def test_compose_does_not_read_files_environment_clock_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = golden_graph("combined")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Composition attempted external I/O")

    with monkeypatch.context() as context:
        context.setattr(builtins, "open", forbidden)
        context.setattr(os, "getenv", forbidden)
        context.setattr(time, "time", forbidden)
        result = compose(graph, ComposeRequest(variables={"project": "Offline"}))
    assert len(result.blocks) == 4
