"""Deterministic permutation and monotonic lock properties."""

from hypothesis import given, settings
from hypothesis import strategies as st
from reliclab.resolve import resolve
from reliclab.vault import CatalogSnapshot, ModuleSnapshot

from tests.support.resolve import catalog, composition
from tests.support.vault import asset

SOURCE = catalog(
    asset(id="base", values=["A"]),
    asset(id="child", extends="base", values=["B"]),
    asset("skill", id="a", version="1.0.0"),
    asset("skill", id="a", version="1.10.0"),
    asset("skill", id="b"),
    asset("memory"),
)
REQUEST = composition(persona="child", skills=["b", "a@1"], memory=["sample"])


@settings(max_examples=60, derandomize=True, database=None, deadline=None)
@given(order=st.permutations(SOURCE.modules))
def test_enumeration_order_cannot_change_graph_or_lock(order: tuple[ModuleSnapshot, ...]) -> None:
    expected = resolve(REQUEST, SOURCE)
    actual = resolve(REQUEST, CatalogSnapshot(tuple(order)))
    assert actual == expected
    assert actual.lock.to_json() == expected.lock.to_json()
    assert actual.lock.digest == expected.lock.digest


@settings(max_examples=60, derandomize=True, database=None, deadline=None)
@given(minor=st.integers(min_value=1, max_value=10000))
def test_new_versions_do_not_modify_locked_selection(minor: int) -> None:
    request = composition(skills=["sample@1"])
    original = resolve(request, catalog(asset("skill")))
    expanded = catalog(asset("skill"), asset("skill", version=f"1.{minor}.0"))
    assert resolve(request, expanded, lock=original.lock) == original
    assert resolve(request, expanded).skills[0].key.version == f"1.{minor}.0"
