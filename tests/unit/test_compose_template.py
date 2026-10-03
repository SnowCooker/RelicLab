"""Scalar-only templates reject expressions and enforce incremental byte limits."""

from collections.abc import Mapping

import pytest
from reliclab.compose.template import substitute
from reliclab.schema import RelicError
from reliclab.schema.types import Scalar


def render(text: str, variables: Mapping[str, Scalar], max_bytes: int = 1024) -> str:
    return substitute(
        text, variables, source="skills/test.md", location=("body",), max_bytes=max_bytes
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("World", "World"), (True, "true"), (False, "false"), (None, "null"), (4, "4"), (1.5, "1.5")],
)
def test_scalars_have_stable_text(value: Scalar, expected: str) -> None:
    assert render("Hello {{ \tvalue }}!", {"value": value}) == f"Hello {expected}!"


@pytest.mark.parametrize(
    "text",
    [
        "{{ user.name }}",
        "{{ user[0] }}",
        "{{ read() }}",
        "{{ x | upper }}",
        "{{ x + 1 }}",
        "{% include 'secret' %}",
        "{% for x in y %}",
        "{# note #}",
        "{{}}",
        "{{ x",
        "x }}",
        "{{{ x }}}",
        "{{ x }}}",
        "{{ x\n }}",
        "{{ \u53d8\u91cf }}",
        "{{ {{ x }} }}",
        pytest.param("{{" * 50000, id="many-unclosed-openers"),
    ],
)
def test_unsupported_syntax_is_rejected_without_disclosing_input(text: str) -> None:
    with pytest.raises(RelicError) as failure:
        render(text, {"x": "secret"})
    assert failure.value.code == "SCHEMA_INVALID"
    assert failure.value.details[0].source == "skills/test.md"
    assert failure.value.details[0].location == ("body",)
    assert "secret" not in str(failure.value)


def test_missing_variable_is_diagnostic_and_replacements_are_not_reparsed() -> None:
    with pytest.raises(RelicError, match="missing") as failure:
        render("{{ private_name }}", {})
    assert "private_name" not in str(failure.value)
    assert failure.value.details[0].location == ("body",)
    assert render("{plain} {{ x }}{{x}}", {"x": "{{ not_executed() }}"}) == (
        "{plain} {{ not_executed() }}{{ not_executed() }}"
    )


def test_byte_limit_counts_unicode_and_combined_expansions() -> None:
    assert render("{{x}}", {"x": "\u4e2d"}, 3) == "\u4e2d"
    for text, variables, limit in [
        ("{{x}}", {"x": "\u4e2d"}, 2),
        ("a{{x}}{{x}}", {"x": "xx"}, 4),
        ("plain", {}, 4),
    ]:
        with pytest.raises(RelicError) as failure:
            render(text, variables, limit)
        assert failure.value.code == "CONTEXT_OVERFLOW"
    with pytest.raises(RelicError, match="UTF-8"):
        render("\ud800", {})
