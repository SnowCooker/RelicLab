"""Cross-check all public examples and canonical golden assets using the real codec."""

import json
from pathlib import Path

import pytest
from reliclab.codec import parse_module, serialize_module
from reliclab.schema import RelicError, validate_module

from scripts.schemas import example_data

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("*/*.md")), ids=lambda p: p.stem)
def test_all_examples_roundtrip_without_writing(path: Path) -> None:
    original = path.read_bytes()
    document = parse_module(original, str(path))
    expected = validate_module(example_data(path)).model_dump()
    normalized = {**document.model_dump(), "body": document.body.replace("\r\n", "\n")}
    assert normalized == expected
    output = serialize_module(document)
    reparsed = parse_module(output)
    body = document.body.replace("\r\n", "\n").replace("\r", "\n")
    if body and not body.endswith("\n"):
        body += "\n"
    assert reparsed.model_dump() == {**document.model_dump(), "body": body}
    assert serialize_module(reparsed) == output
    assert path.read_bytes() == original


@pytest.mark.parametrize("kind", ["persona", "skill", "memory", "composition"])
def test_golden_canonical_documents(kind: str) -> None:
    directory = ROOT / "tests/fixtures/codec"
    document = parse_module((directory / f"{kind}.input.md").read_bytes())
    expected = (directory / f"{kind}.canonical.md").read_text(encoding="utf-8")
    assert serialize_module(document) == expected
    assert serialize_module(parse_module(expected)) == expected


@pytest.mark.parametrize("path", sorted((ROOT / "tests/fixtures/invalid").glob("*.json")))
def test_invalid_schema_fixtures_remain_invalid_through_codec(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))["document"]
    body = document.pop("body", "")
    with pytest.raises(RelicError) as caught:
        parse_module("---\n" + json.dumps(document) + "\n---\n" + body)
    assert caught.value.code == "SCHEMA_INVALID"
