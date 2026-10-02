"""Exercise strict asset contracts, portable primitives, and safe diagnostics."""

import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from reliclab.schema import (
    AssetVersion,
    Composition,
    Memory,
    ModuleId,
    ModuleRef,
    ModuleSelection,
    Persona,
    RelicError,
    RenderOptions,
    Skill,
    ToolRequirement,
    validate_module,
)
from reliclab.schema.types import nonblank, semantic_version


def asset(kind: str = "persona", **changes: Any) -> dict[str, Any]:
    fields: dict[str, dict[str, Any]] = {
        "persona": {"identity": "A careful editor"},
        "skill": {"body": "Review the code."},
        "memory": {"source": "inline", "body": "Project notes."},
        "composition": {"modules": {"skills": ["review-code"]}, "render": {"target": "plain"}},
    }
    return {
        "schema_version": "1.0",
        "kind": kind,
        "id": "sample",
        "version": "1.0.0",
        "name": "Sample",
        **fields.get(kind, {}),
        **changes,
    }


@pytest.mark.parametrize(
    "kind,model",
    [
        ("persona", Persona),
        ("skill", Skill),
        ("memory", Memory),
        ("composition", Composition),
    ],
)
def test_model_defaults_key_and_json_roundtrip(kind: str, model: type[Any]) -> None:
    result = validate_module(asset(kind))
    assert isinstance(result, model)
    assert result.key.id == "sample"
    assert hash(result.key)
    assert result.description == ""
    assert result.tags == ()
    assert result.extensions == {}
    assert validate_module(json.loads(result.model_dump_json())) == result
    assert model.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    "modules",
    [
        {"persona": "editor", "skills": ["review"], "memory": ["notes"]},
        {"skills": ["review"], "memory": ["notes"]},
        {"persona": "editor", "memory": ["notes"]},
        {"memory": ["notes"]},
        {"persona": "editor"},
        {"skills": ["review"]},
        {"persona": "editor", "skills": ["review"]},
    ],
)
def test_all_nonempty_selection_modes(modules: dict[str, Any]) -> None:
    result = validate_module(asset("composition", modules=modules))
    assert isinstance(result, Composition)
    assert result.render.token_budget == 8000


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "2.0"),
        ("schema_version", 1.0),
        ("id", "Upper"),
        ("id", "a_b"),
        ("id", "a/b"),
        ("id", "a\n"),
        ("id", ""),
        ("id", "a" * 65),
        ("id", "con"),
        ("id", "nul"),
        ("id", "com1"),
        ("id", "lpt9"),
        ("id", "prn"),
        ("id", "aux"),
        ("version", "1"),
        ("version", "1.2"),
        ("version", "01.2.3"),
        ("version", "1.2.3-01"),
        ("version", "v1.2.3"),
        ("version", "^1.2.3"),
        ("version", "1.2.3\n"),
        ("name", " \t"),
        ("name", "a" * 121),
        ("description", "a" * 2001),
        ("author", "a" * 121),
        ("tags", ["a"] * 33),
        ("tags", ["a" * 65]),
        ("tags", [1]),
        ("tags", "tag"),
        ("tags", {"tag"}),
        ("tags", {"tag": "value"}),
        ("extensions", {"plugin": True}),
        ("extensions", {"x-value": object()}),
        ("extensions", {"x-number": float("inf")}),
        ("identity", " \t"),
        ("identity", True),
        ("values", [False]),
        ("voice", 123),
        ("body", b"bytes"),
        ("unexpected", "hidden-secret"),
    ],
)
def test_common_invalid_fields(field: str, value: Any) -> None:
    with pytest.raises(RelicError) as raised:
        validate_module(asset(**{field: value}), source="sample.md")
    error = raised.value
    assert error.code == "SCHEMA_INVALID"
    assert error.location[0] == field
    assert error.details[0].source == "sample.md"
    assert error.details[0].severity == "error"
    assert error.retryable is False
    assert "hidden-secret" not in str(error)
    assert "hidden-secret" not in repr(error.details)


@pytest.mark.parametrize("data", [None, [], "asset", {}, {"kind": "unknown"}])
def test_invalid_document_has_stable_root_error(data: Any) -> None:
    with pytest.raises(RelicError) as raised:
        validate_module(data)
    assert raised.value.location == ()


def test_common_limits_accept_exact_boundaries() -> None:
    result = validate_module(
        asset(
            id="a" * 64,
            name="n" * 120,
            description="d" * 2000,
            author="a" * 120,
            tags=[str(index).zfill(64) for index in range(32)],
        )
    )
    assert len(result.tags) == 32


@pytest.mark.parametrize(
    "document,location",
    [
        (
            asset("composition", render={"target": "plain", "token_budget": "8000"}),
            ("render", "token_budget"),
        ),
        (asset("composition", modules={"skills": ["review@1", "review@2"]}), ("modules", "skills")),
        (
            asset(
                "skill",
                tools=[{"name": "BAD", "description": "", "input_schema": {"type": "object"}}],
            ),
            ("tools", 0, "name"),
        ),
    ],
)
def test_nested_diagnostic_locations(
    document: dict[str, Any], location: tuple[str | int, ...]
) -> None:
    with pytest.raises(RelicError) as raised:
        validate_module(document)
    assert raised.value.location == location


@pytest.mark.parametrize("version", ["0.0.0", "1.2.3-rc.1", "1.0.0+build.2026", "2.0.0-a.0+ci"])
def test_semver_storage_versions(version: str) -> None:
    assert validate_module(asset(version=version)).version == version


@pytest.mark.parametrize(
    "reference",
    [
        "editor",
        "editor@1",
        "editor@1.2",
        "editor@1.2.3",
        "editor@^1.2.0",
        "editor@^0.2.3",
        "editor@1.2.3-rc.1+ci",
        "editor@^1.2.3-rc.1",
    ],
)
def test_supported_references(reference: str) -> None:
    assert TypeAdapter(ModuleRef).validate_python(reference) == reference


@pytest.mark.parametrize(
    "reference",
    [
        "con",
        "con@1",
        "aux@^1.2.3",
        "editor@",
        "editor@01",
        "editor@1.02",
        "editor@~1.0.0",
        "editor@*",
        "editor@>=1.0.0",
        "editor@latest",
        "editor@1.0.0-01",
        "editor@^1.2",
        "editor@1.2.3.4",
        "editor\n",
    ],
)
def test_unsupported_references(reference: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ModuleRef).validate_python(reference)


@pytest.mark.parametrize("kind", ["skill", "memory", "composition"])
def test_only_persona_can_extend(kind: str) -> None:
    with pytest.raises(RelicError) as raised:
        validate_module(asset(kind, extends="editor"))
    assert raised.value.location == ("extends",)


@pytest.mark.parametrize(
    "source,path", [("file", "project/notes.md"), ("glob", "research/**/*.md")]
)
def test_external_memory(source: str, path: str) -> None:
    result = validate_module(
        asset("memory", source=source, root="notes", path=path, body="", depth=1)
    )
    assert isinstance(result, Memory)
    assert result.path == path


@pytest.mark.parametrize(
    "changes",
    [
        {"root": "notes"},
        {"path": "notes.md"},
        {"body": ""},
        {"body": "  "},
        {"source": "file"},
        {"source": "glob", "root": "notes"},
        {"source": "file", "root": "notes", "path": "notes.md"},
        {"source": "file", "root": "notes", "path": "*.md", "body": ""},
        {"depth": -1},
        {"depth": 2},
        {"depth": True},
        {"depth": "1"},
        {"depth": 1.0},
        {"scope": "sometimes"},
        {"source": "https"},
    ],
)
def test_memory_conflicts(changes: dict[str, Any]) -> None:
    with pytest.raises(RelicError):
        validate_module(asset("memory", **changes))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/notes.md",
        "../notes.md",
        "a/../notes.md",
        "./notes.md",
        "a//notes.md",
        "C:/notes.md",
        "C:notes.md",
        "\\\\server\\share",
        "https://example.test/a",
        "a\\notes.md",
        "nul.md",
        "a/CON.txt",
        "NUL .txt",
        "COM\u00b9.txt",
        "lpt\u00b2.md",
        "a/",
        "a. /b",
        "a./b",
        "a\x00.md",
        "a\n.md",
        'a".md',
        "a<.md",
        "a|.md",
    ],
)
def test_portable_memory_paths(path: str) -> None:
    with pytest.raises(RelicError) as raised:
        validate_module(asset("memory", source="file", root="notes", path=path, body=""))
    assert raised.value.location == ("path",)


@pytest.mark.parametrize("budget", [0, -1, 1_000_001, "8000", True, 1.5, 1.0])
def test_strict_budget(budget: Any) -> None:
    with pytest.raises(ValidationError):
        RenderOptions.model_validate({"target": "plain", "token_budget": budget})


@pytest.mark.parametrize("budget", [1, 8000, 1_000_000])
def test_valid_budget(budget: int) -> None:
    assert RenderOptions(target="plain", token_budget=budget).token_budget == budget


@pytest.mark.parametrize(
    "selection",
    [
        {},
        {"persona": None, "skills": [], "memory": []},
        {"skills": ["review@1", "review@2"]},
        {"memory": ["notes", "notes"]},
    ],
)
def test_empty_or_duplicate_selection(selection: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ModuleSelection.model_validate(selection)


def test_same_id_across_different_slots_is_valid() -> None:
    assert ModuleSelection.model_validate({"skills": ["notes"], "memory": ["notes"]})


@pytest.mark.parametrize("value", [[], {}, float("nan"), float("inf"), object()])
def test_variables_are_finite_scalars(value: Any) -> None:
    with pytest.raises(RelicError):
        validate_module(asset("composition", variables={"value": value}))


def test_scalar_types_are_preserved() -> None:
    values = {"text": "1", "integer": 1, "float": 1.2, "flag": True, "nothing": None}
    result = validate_module(asset("composition", variables=values))
    assert isinstance(result, Composition)
    assert {key: type(value) for key, value in result.variables.items()} == {
        key: type(value) for key, value in values.items()
    }


def test_body_byte_boundary_and_surrogate_rejection() -> None:
    assert len(validate_module(asset(body="x" * 1_048_576)).body) == 1_048_576
    for body in ("x" * 1_048_577, "\u4e2d" * 349_526, "\ud800"):
        with pytest.raises(RelicError):
            validate_module(asset(body=body))


@pytest.mark.parametrize("body", ["", " \n\t"])
def test_skill_needs_instructions(body: str) -> None:
    with pytest.raises(RelicError):
        validate_module(asset("skill", body=body))


def test_collection_copying_normalization_and_frozen_fields() -> None:
    data = asset(
        name="  Editor  ",
        tags=["first", "second", "first"],
        values=["quality"],
        extensions={"x-plugin": {"items": [1, 2]}},
    )
    before = deepcopy(data)
    result = validate_module(data)
    assert result.name == "Editor"
    assert result.tags == ("first", "second")
    data["values"].append("changed")
    data["extensions"]["x-plugin"]["items"].append(3)
    assert isinstance(result, Persona)
    assert result.values == ("quality",)
    assert result.extensions == before["extensions"]
    dumped = result.model_dump(mode="json")
    dumped["extensions"]["x-plugin"]["items"].append(4)
    assert result.extensions == before["extensions"]
    with pytest.raises(ValidationError):
        result.name = "Changed"


def test_untrusted_model_instance_is_revalidated() -> None:
    forged = Persona.model_construct(**asset(id="BAD"))
    with pytest.raises(RelicError):
        validate_module(forged)


def test_primitive_validation_failures_are_actionable() -> None:
    with pytest.raises(ValueError, match="non-whitespace"):
        nonblank(" ")
    assert nonblank("text") == "text"
    with pytest.raises(ValueError):
        semantic_version("not-a-version")


@pytest.mark.parametrize(
    "alias,value",
    [
        (ModuleId, "sample"),
        (ModuleRef, "sample@1"),
        (AssetVersion, "1.0.0"),
    ],
)
def test_public_primitive_aliases_are_strict_without_config(alias: Any, value: str) -> None:
    adapter = TypeAdapter(alias)
    assert adapter.validate_python(value) == value
    for bad in (value.encode(), 1, True, value + "\n"):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_tool_subset_nested_schema_and_defensive_copy() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"}},
            "options": {"type": "object", "properties": {"recursive": {"type": "boolean"}}},
        },
        "required": ["paths"],
        "additionalProperties": False,
    }
    tool = ToolRequirement(name="read_files", input_schema=schema, description="Read files")
    schema["properties"]["paths"]["items"]["type"] = "number"
    assert tool.model_dump()["input_schema"]["properties"]["paths"]["items"]["type"] == "string"


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"type": "unknown"},
        {"type": "string"},
        {"type": ["object", "null"]},
        {"type": "object", "$ref": "https://example.invalid/schema"},
        {"type": "object", "$ref": "file:///secret"},
        {"type": "object", "additionalProperties": "false"},
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"type": "object", "required": ["path", "path"]},
        {"type": "object", "items": {"type": "string"}},
        {"type": "object", "properties": {"path": {"type": "array"}}},
        {"type": "object", "properties": {"path": {"type": "string", "properties": {}}}},
        {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}}},
        {"type": "object", "properties": {"path": True}},
    ],
)
def test_unsupported_tool_schemas_fail_offline(schema: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ToolRequirement(name="read", input_schema=schema, description="Read")


@pytest.mark.parametrize("name", ["Read", "read-file", "read\n", "a" * 65])
def test_invalid_tool_names(name: str) -> None:
    with pytest.raises(ValidationError):
        ToolRequirement(name=name, input_schema={"type": "object"}, description="Read")
