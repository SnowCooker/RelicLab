"""Deterministic generated Unicode and recursive JSON roundtrip checks."""

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from reliclab.codec import parse_module, serialize_module
from reliclab.schema import RelicError, validate_module

text = st.text(alphabet=st.characters(exclude_categories=["Cs"]), max_size=80)
scalars: st.SearchStrategy[Any] = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**30), max_value=10**30),
    st.floats(allow_nan=False, allow_infinity=False),
    text,
)
values = st.recursive(
    scalars,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(text, children, max_size=4),
    max_leaves=20,
)


@settings(max_examples=150, derandomize=True, database=None, deadline=None)
@given(kind=st.sampled_from(["persona", "skill", "memory", "composition"]), body=text, value=values)
def test_canonical_semantic_roundtrip(kind: str, body: str, value: Any) -> None:
    required: dict[str, dict[str, Any]] = {
        "persona": {"identity": "Editor"},
        "skill": {},
        "memory": {"source": "inline"},
        "composition": {"modules": {"skills": ["review"]}, "render": {"target": "plain"}},
    }
    document = validate_module(
        {
            "schema_version": "1.0",
            "id": "sample",
            "kind": kind,
            "version": "1.0.0",
            "name": "Sample",
            "body": "Notes: " + body,
            "extensions": {"x-data": value},
            **required[kind],
        }
    )
    output = serialize_module(document)
    parsed = parse_module(output.encode("utf-8"))
    normalized = document.body.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    assert parsed.model_dump() == {**document.model_dump(), "body": normalized}
    assert serialize_module(parsed) == output


@settings(max_examples=100, derandomize=True, database=None, deadline=None)
@given(header=text, body=text)
def test_arbitrary_text_never_escapes_domain_error_contract(header: str, body: str) -> None:
    try:
        parse_module(f"---\n{header}\n---\n{body}")
    except RelicError as error:
        assert error.code in ("PARSE_ERROR", "SCHEMA_INVALID")
        assert error.details


@settings(max_examples=100, derandomize=True, database=None, deadline=None)
@given(raw=st.binary(max_size=300))
def test_arbitrary_bytes_never_escape_domain_error_contract(raw: bytes) -> None:
    try:
        parse_module(b"---\n" + raw + b"\n---\n")
    except RelicError as error:
        assert error.code in ("PARSE_ERROR", "SCHEMA_INVALID")
        assert error.details
