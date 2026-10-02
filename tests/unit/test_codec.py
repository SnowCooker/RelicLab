"""Exercise the production codec's envelope, source mapping, and bounded YAML subset."""

import builtins
import json
import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import yaml
from reliclab.codec import (
    CodecLimits,
    SourcePosition,
    parse_module,
    parse_with_source,
    serialize_module,
)
from reliclab.schema import RelicError, validate_module

HEADER = (
    'schema_version: "1.0"\nid: sample\nkind: persona\nversion: 1.0.0\n'
    "name: Sample\nidentity: Editor\n"
)


def markdown(header: str = HEADER, body: str = "") -> str:
    return f"---\n{header}---\n{body}"


@pytest.mark.parametrize("bom", ["", "\ufeff"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("as_bytes", [False, True])
def test_bom_newlines_and_body_preservation(bom: str, newline: str, as_bytes: bool) -> None:
    text = bom + markdown(body="Notes\n---\n\u4e2d\u6587\n\n").replace("\n", newline)
    result = parse_with_source(text.encode("utf-8") if as_bytes else text, "sample.md")
    assert result.document.body == f"Notes{newline}---{newline}\u4e2d\u6587{newline}{newline}"
    assert result.positions[("identity",)] == SourcePosition(7, 11)
    assert result.positions[("body",)] == SourcePosition(9, 1)
    canonical = serialize_module(result.document)
    assert not canonical.startswith("\ufeff")
    assert "\r" not in canonical
    assert canonical.endswith("Notes\n---\n\u4e2d\u6587\n\n")


@pytest.mark.parametrize("text", [markdown(), markdown().removesuffix("\n")])
def test_empty_body_and_closing_delimiter_at_eof(text: str) -> None:
    assert parse_module(text).body == ""
    expected = SourcePosition(9, 1) if text.endswith("\n") else SourcePosition(8, 4)
    assert parse_with_source(text).positions[("body",)] == expected


def test_bare_cr_at_header_eof_is_rejected() -> None:
    with pytest.raises(RelicError, match="line endings"):
        parse_module("---\nname: Sample\r")
    with pytest.raises(RelicError, match="line endings"):
        parse_module("---\n---\r")


@pytest.mark.parametrize(
    "text", ["", "---", "---\r", " ---\n", "--- # header\n", "\n---\n", "\ufeff\ufeff" + markdown()]
)
def test_opening_boundary_is_exact(text: str) -> None:
    with pytest.raises(RelicError, match="must start") as caught:
        parse_module(text)
    assert caught.value.details[0].line == 1


@pytest.mark.parametrize(
    "text",
    [
        "---\n",
        "---\nname: Sample",
        "---\nname: Sample\n",
        "---\n--- # not the envelope delimiter\n",
    ],
)
def test_missing_closing_boundary(text: str) -> None:
    with pytest.raises(RelicError, match="Missing closing"):
        parse_module(text)


@pytest.mark.parametrize("text", [b"\xff", "\ud800", markdown(body="\udfff")])
def test_invalid_utf8_is_redacted(text: str | bytes) -> None:
    with pytest.raises(RelicError, match="valid UTF-8") as caught:
        parse_module(text, "asset.md")
    diagnostic = caught.value.details[0]
    assert diagnostic.source == "asset.md"
    assert diagnostic.exact is False
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("separator", ["\r", "\x85", "\u2028", "\u2029"])
def test_unsupported_header_line_breaks(separator: str) -> None:
    with pytest.raises(RelicError, match="line endings"):
        parse_module(markdown(f"name: one{separator}two\n"))


def test_exact_byte_limits_count_utf8_and_raw_crlf() -> None:
    header = HEADER.replace("Editor", "\u4e2d\u6587")
    body = "\u4e2d\u6587"
    limits = CodecLimits(max_frontmatter_bytes=len(header.encode()), max_body_bytes=6)
    assert parse_module(markdown(header, body), limits=limits).body == body
    with pytest.raises(RelicError, match="Body exceeds"):
        parse_module(markdown(header, body + "x"), limits=limits)
    with pytest.raises(RelicError, match="Frontmatter exceeds"):
        parse_module(markdown(header + "\n", body), limits=limits)
    with pytest.raises(RelicError, match="Frontmatter exceeds"):
        parse_module(markdown(header, body).replace("\n", "\r\n"), limits=limits)
    with pytest.raises(RelicError, match="Body exceeds"):
        serialize_module(parse_module(markdown(header, body)), limits=CodecLimits(max_body_bytes=6))


@pytest.mark.parametrize("as_bytes", [False, True])
def test_combined_size_is_rejected_before_decoding(as_bytes: bool) -> None:
    value = "x" * 16
    with pytest.raises(RelicError, match="combined byte limit"):
        parse_module(
            value.encode() if as_bytes else value,
            limits=CodecLimits(max_frontmatter_bytes=1, max_body_bytes=1),
        )


def test_host_can_raise_body_limit_without_metadata_override() -> None:
    body = "x" * (1024 * 1024 + 1)
    with pytest.raises(RelicError, match="Body exceeds"):
        parse_module(markdown(body=body))
    limits = CodecLimits(max_body_bytes=len(body) + 1)
    document = parse_module(markdown(body=body), limits=limits)
    assert (
        parse_module(serialize_module(document, limits=limits), limits=limits).body == body + "\n"
    )
    with pytest.raises(RelicError):
        validate_module(document)
    with pytest.raises(RelicError) as caught:
        parse_module(markdown(HEADER + "max_body_bytes: 999999999\n"))
    assert caught.value.code == "SCHEMA_INVALID"


@pytest.mark.parametrize(
    "field", ["max_frontmatter_bytes", "max_body_bytes", "max_depth", "max_nodes"]
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_limits_are_strict_positive_integers(field: str, value: Any) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        CodecLimits(**{field: value})


def test_hard_depth_ceiling_and_immutable_limits() -> None:
    assert CodecLimits(max_depth=64).max_depth == 64
    with pytest.raises(ValueError, match="ceiling"):
        CodecLimits(max_depth=65)
    with pytest.raises(FrozenInstanceError):
        limits: Any = CodecLimits()
        limits.max_nodes = 0


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_schema_host_limit_validation(limit: Any) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        validate_module({}, max_body_bytes=limit)


@pytest.mark.parametrize("header", ["", "[]\n", "null\n", "just text\n"])
def test_root_must_be_mapping(header: str) -> None:
    with pytest.raises(RelicError, match="must be a mapping"):
        parse_module(markdown(header))


@pytest.mark.parametrize("key", ["1", "true", "null", "[a, b]", "{a: b}", "?"])
def test_non_string_mapping_keys(key: str) -> None:
    with pytest.raises(RelicError):
        parse_module(markdown(f"{key}: value\n"))


@pytest.mark.parametrize(
    "header",
    [
        "a: 1\na: 2\n",
        '"a": 1\n"\\u0061": 2\n',
        "x: {a: 1, a: 2}\n",
        "<<: {}\n",
        '"\\ud83d\\ude00": 1\n"\U0001f600": 2\n',
    ],
)
def test_duplicate_and_merge_keys_are_rejected(header: str) -> None:
    with pytest.raises(RelicError, match="duplicate keys") as caught:
        parse_module(markdown(header), "duplicate.md")
    assert caught.value.details[0].exact


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("false", False),
        ("null", None),
        ("", None),
        ("-12", -12),
        ("1e3", 1000.0),
        ("1.25", 1.25),
        ("yes", "yes"),
        ("on", "on"),
        ("~", "~"),
        ("01", "01"),
        ("0x10", "0x10"),
        ("1:20", "1:20"),
        (".inf", ".inf"),
        ("2026-10-02", "2026-10-02"),
        ('"true"', "true"),
        ('""', ""),
        ('"\\ud83d\\ude00"', "\U0001f600"),
        ("|\n    notes\n", "notes\n"),
    ],
)
def test_documented_scalar_subset(value: str, expected: Any) -> None:
    document = parse_module(markdown(HEADER + f"extensions:\n  x-value: {value}\n"))
    assert document.extensions["x-value"] == expected
    assert type(document.extensions["x-value"]) is type(expected)


@pytest.mark.parametrize(
    "value",
    ["1e999", '"\\ud800"', '"\\udfff"', "9" * 5000],
    ids=["overflow", "high-surrogate", "low-surrogate", "large-number"],
)
def test_invalid_scalar_fails_safely_in_values_and_keys(value: str) -> None:
    for header in (f"a: {value}\n", f"? {value}\n: a\n"):
        with pytest.raises(RelicError, match="Invalid UTF-8 scalar or numeric value"):
            parse_module(markdown(header))


def test_source_map_is_read_only_and_nested_errors_have_exact_positions() -> None:
    header = (
        'schema_version: "1.0"\nid: sample\nkind: composition\nversion: 1.0.0\n'
        "name: Sample\nmodules:\n  skills:\n    - review\nrender:\n  target: plain\n"
        "  token_budget: 8\n"
    )
    result = parse_with_source(markdown(header))
    assert result.positions[("modules", "skills", 0)] == SourcePosition(9, 7)
    assert result.positions[("render", "token_budget")] == SourcePosition(12, 17)
    with pytest.raises(TypeError):
        result.positions[("name",)] = SourcePosition(1, 1)  # type: ignore[index]
    with pytest.raises(RelicError) as caught:
        parse_module(
            markdown(header.replace("token_budget: 8", 'token_budget: "secret"')), "composition.md"
        )
    detail = caught.value.details[0]
    assert (detail.line, detail.column, detail.exact) == (12, 17, True)
    assert detail.location == ("render", "token_budget")
    assert "secret" not in str(caught.value) + repr(caught.value.details)


def test_missing_fields_use_documented_fallback_not_invented_positions() -> None:
    with pytest.raises(RelicError) as caught:
        parse_module(markdown(HEADER.replace("identity: Editor\n", "")))
    detail = caught.value.details[0]
    assert detail.location == ("identity",)
    assert (detail.line, detail.column, detail.exact) == (2, 1, False)


def test_body_schema_error_and_metadata_body_rejection() -> None:
    with pytest.raises(RelicError) as caught:
        parse_module(markdown(HEADER.replace("persona", "skill").replace("identity: Editor\n", "")))
    assert caught.value.details[0].location == ("body",)
    assert caught.value.details[0].line == 8
    with pytest.raises(RelicError, match="metadata field") as caught:
        parse_module(markdown(HEADER + "body: injected\n", "actual"))
    assert caught.value.details[0].line == 8


def test_malformed_yaml_reports_mark_and_suppresses_raw_context() -> None:
    with pytest.raises(RelicError, match="Malformed YAML") as caught:
        parse_module(markdown("a: [private-value\n"))
    assert caught.value.details[0].line == 3
    assert "private-value" not in str(caught.value)
    assert caught.value.__suppress_context__
    with pytest.raises(RelicError) as caught:
        parse_module(markdown("a: \x00\n"))
    assert caught.value.details[0].exact is False


@pytest.mark.security
@pytest.mark.parametrize(
    "payload",
    [
        'x: !!python/object/apply:os.system ["touch should-not-exist"]\n',
        'x: !!python/object/new:subprocess.Popen [["whoami"]]\n',
        "x: !!python/name:builtins.open ''\n",
        "x: !!str value\n",
        "x: !custom value\n",
        "x: &shared [1, 2]\ny: *shared\n",
        "x: *undefined\n",
        "x: &recursive [*recursive]\n",
        "%YAML 1.2\n--- # start\nx: y\n",
        "%TAG !e! tag:example.com,2026:\n--- # start\nx: y\n",
        "a: 1\n--- # another document\na: 2\n",
        "a: 1\n...\n",
    ],
)
def test_untrusted_yaml_has_no_file_or_process_effects(
    payload: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        calls.append("effect")
        raise AssertionError("Codec attempted a side effect")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(os, "system", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(yaml.BaseLoader, "construct_object", forbidden)
        with pytest.raises(RelicError) as caught:
            parse_module(markdown(payload))
    assert caught.value.code == "PARSE_ERROR"
    assert calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.security
def test_nesting_and_node_limits_fail_before_tree_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Over-limit input reached tree composition")

    monkeypatch.setattr(yaml, "compose", forbidden)
    with pytest.raises(RelicError, match="nesting limit"):
        parse_module(markdown("a: " + "[" * 1000 + "0" + "]" * 1000 + "\n"))
    with pytest.raises(RelicError, match="node limit"):
        parse_module(markdown(HEADER), limits=CodecLimits(max_nodes=2))


def test_limits_accept_exact_node_and_depth_boundary() -> None:
    assert parse_module(markdown(), limits=CodecLimits(max_nodes=13, max_depth=2)).id == "sample"
    with pytest.raises(RelicError, match="node limit"):
        parse_module(markdown(), limits=CodecLimits(max_nodes=12))
    with pytest.raises(RelicError, match="nesting limit"):
        parse_module(markdown(), limits=CodecLimits(max_depth=1))


def test_canonical_output_ignores_mapping_order_and_preserves_sequence_order() -> None:
    first = parse_module(markdown(HEADER + "extensions: {x-z: [3, 1], x-a: {z: 1, a: 2}}\n"))
    second = parse_module(markdown(HEADER + "extensions: {x-a: {a: 2, z: 1}, x-z: [3, 1]}\n"))
    assert serialize_module(first) == serialize_module(second)
    assert parse_module(serialize_module(first)).extensions["x-z"] == [3, 1]


def test_serializer_revalidates_mutated_mapping_and_unsafe_model_copy() -> None:
    document = parse_module(markdown())
    document.extensions["bad"] = "value"
    with pytest.raises(RelicError):
        serialize_module(document)
    with pytest.raises(RelicError):
        serialize_module(parse_module(markdown()).model_copy(update={"id": "INVALID"}))


def test_comments_and_line_endings_are_explicit_canonical_changes() -> None:
    document = parse_module(markdown("# private comment\n" + HEADER, "one\rtwo\r\nthree"))
    output = serialize_module(document)
    assert "private comment" not in output
    assert output.endswith("one\ntwo\nthree\n")
    assert document.body == "one\rtwo\r\nthree"
    assert serialize_module(parse_module(output)) == output


def test_json_frontmatter_equivalence() -> None:
    document = parse_module(markdown())
    data = document.model_dump(mode="json", exclude={"body"})
    assert parse_module(markdown(json.dumps(data) + "\n")) == document


def test_unencodable_integer_has_domain_error_without_raw_context() -> None:
    document = parse_module(markdown())
    document.extensions["x-large"] = 10**5000
    with pytest.raises(RelicError) as caught:
        serialize_module(document)
    assert caught.value.code == "SCHEMA_INVALID"
    assert caught.value.details[0].line is None
    assert caught.value.__suppress_context__
