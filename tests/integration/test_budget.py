"""Budgeting real captured assets changes context, not the Vault or its lock."""

from pathlib import Path

import pytest
from reliclab.compose import ComposeRequest, compose
from reliclab.resolve import resolve
from reliclab.schema import RelicError
from reliclab.vault import Vault

from tests.support.resolve import composition
from tests.support.vault import asset


def test_three_budgets_preserve_vault_bytes_and_locked_sources(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.create(asset())
    vault.create(asset("memory", body="Optional notes.\n"))
    before = vault.snapshot()
    graph = resolve(composition(persona="sample", memory=["sample"]), before)
    full = compose(graph, ComposeRequest(selected_memory_ids=("sample",)))
    minimum = full.budget_report.required_tokens
    trimmed = compose(graph, ComposeRequest(selected_memory_ids=("sample",), token_budget=minimum))
    with pytest.raises(RelicError) as failure:
        compose(graph, ComposeRequest(selected_memory_ids=("sample",), token_budget=minimum - 1))
    assert failure.value.code == "CONTEXT_OVERFLOW"
    assert len(full.blocks) == 2 and len(trimmed.blocks) == 1
    assert len(trimmed.budget_report.omissions) == 1
    assert full.manifest.composition_lock == trimmed.manifest.composition_lock == graph.lock
    assert vault.snapshot() == before
