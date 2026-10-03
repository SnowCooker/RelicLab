"""Compose captured vault bytes without hidden reads or source modification."""

import hashlib
from pathlib import Path

from reliclab.compose import compose
from reliclab.resolve import resolve
from reliclab.vault import Vault

from tests.support.resolve import composition
from tests.support.vault import asset


def test_vault_snapshot_to_ir_preserves_original_bytes(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    saved = vault.create(asset(body="Original.\n"))
    root = composition(persona="sample")
    captured = vault.snapshot()
    graph = resolve(root, captured)
    context = compose(graph)
    block = context.blocks[0]
    path = tmp_path / "vault" / saved.relative_path
    assert block.source_hash == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.read_bytes() == saved.content
    replacement = asset(body="Updated.\n")
    vault.update(saved.key, replacement, saved.content_hash)
    assert compose(graph).to_json() == context.to_json()
    assert compose(resolve(root, vault.snapshot())).digest != context.digest
