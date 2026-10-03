"""Stable full-IR golden files and source-sensitive deterministic composition."""

from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from reliclab.compose import ComposeRequest, compose
from reliclab.resolve import resolve

from tests.support.compose import golden_graph
from tests.support.resolve import catalog, composition
from tests.support.vault import asset

FIXTURES = Path(__file__).parents[1] / "fixtures" / "compose"


@pytest.mark.parametrize("mode", ["persona", "skill", "memory", "combined"])
def test_full_ir_golden(mode: str) -> None:
    graph = golden_graph(mode)
    request = ComposeRequest(variables={"project": "RelicLab"})
    result = compose(graph, request)
    assert result.to_json() + "\n" == (FIXTURES / f"{mode}.json").read_text(encoding="utf-8")
    for _ in range(100):
        repeated = compose(graph, request)
        assert repeated.to_json() == result.to_json()
        assert repeated.digest == result.digest


@pytest.mark.parametrize("kind", ["persona", "skill", "memory"])
@settings(max_examples=30, derandomize=True, database=None, deadline=None)
@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="{}"),
        max_size=80,
    )
)
def test_every_source_body_changes_digest(kind: str, suffix: str) -> None:
    slots: dict[str, dict[str, Any]] = {
        "persona": {"persona": "sample"},
        "skill": {"skills": ["sample"]},
        "memory": {"memory": ["sample"]},
    }
    root = composition(**slots[kind])
    original = compose(resolve(root, catalog(asset(kind, body="Before\n"))))
    changed = compose(resolve(root, catalog(asset(kind, body="After " + suffix + "\n"))))
    assert original.digest != changed.digest


def test_canonical_request_sets_and_dictionary_order() -> None:
    graph = golden_graph("combined")
    trusted = tuple(item for item in graph.lock.modules if item.key.kind != "memory")
    first = compose(
        graph, ComposeRequest(variables={"project": "A", "unused": 1}, trusted_sources=trusted)
    )
    second = compose(
        graph,
        ComposeRequest(variables={"unused": 1, "project": "A"}, trusted_sources=trusted[::-1]),
    )
    assert first.to_json() == second.to_json()
    assert first.digest != compose(graph, ComposeRequest(variables={"project": "B"})).digest
    assert (
        first.digest
        != compose(graph, ComposeRequest(variables={"project": "A", "unused": 1})).digest
    )
