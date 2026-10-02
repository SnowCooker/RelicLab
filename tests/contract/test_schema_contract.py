"""Keep generated schemas, examples, and semantic differences reproducible."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from reliclab.schema import RelicError, json_schema, schema_text, validate_module

from scripts import schemas

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind", ["persona", "skill", "memory", "composition", None])
def test_schema_is_valid_stable_and_matches_checked_in_file(kind: str | None) -> None:
    schema = json_schema(kind)
    Draft202012Validator.check_schema(schema)
    assert schema_text(kind) == (ROOT / "schemas" / f"{kind or 'module'}.schema.json").read_text(
        encoding="utf-8"
    )
    schema["corruption"] = True
    assert "corruption" not in json_schema(kind)


@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("*/*.md")), ids=lambda p: p.stem)
def test_examples_validate_before_and_after_normalization(path: Path) -> None:
    data = schemas.example_data(path)
    kind = data["kind"]
    for schema in (json_schema(), json_schema(kind)):
        validator = Draft202012Validator(schema)
        validator.validate(data)
        document = validate_module(data, source=path.name)
        validator.validate(document.model_dump(mode="json"))
        assert document.key.kind == path.parent.name
        assert path.name == f"{document.id}@{document.version}.md"


@pytest.mark.parametrize("path", sorted((ROOT / "tests/fixtures/invalid").glob("*.json")))
def test_invalid_fixture_contract(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(RelicError):
        validate_module(fixture["document"])
    assert (
        Draft202012Validator(json_schema()).is_valid(fixture["document"])
        == fixture["structural_valid"]
    )


def test_repository_verifier_and_schema_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert schemas.main(["--check"]) == 0
    monkeypatch.setattr(schemas, "ROOT", tmp_path)
    assert schemas.main(["--check"]) == 1
    monkeypatch.setattr(schemas, "verify", lambda root: None)
    assert schemas.main([]) == 0
    assert schemas.main(["--check"]) == 0
    (tmp_path / "schemas/persona.schema.json").write_text("{}", encoding="utf-8")
    assert schemas.main(["--check"]) == 1


@pytest.mark.parametrize("content", ["", "text", "---\nbody: forbidden\n---\n", "---\n[]\n---\n"])
def test_example_reader_rejects_invalid_fixture_shape(tmp_path: Path, content: str) -> None:
    path = tmp_path / "example.md"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        schemas.example_data(path)


def test_verifier_rejects_missing_examples(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="three persona"):
        schemas.verify(tmp_path)


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"modules": {}}, False),
        ({"modules": {"persona": None}}, False),
        ({"modules": {"skills": []}}, False),
        ({"modules": {"memory": ["notes"]}}, True),
    ],
)
def test_schema_nonempty_selection(data: dict[str, Any], expected: bool) -> None:
    document = {
        "schema_version": "1.0",
        "kind": "composition",
        "id": "sample",
        "version": "1.0.0",
        "name": "Sample",
        "render": {"target": "plain"},
        **data,
    }
    assert Draft202012Validator(json_schema("composition")).is_valid(document) == expected
