"""Real Vault snapshots, stable lock replay, and external-change detection."""

from pathlib import Path

import pytest
from reliclab.resolve import CompositionLock, ResolutionError, resolve
from reliclab.schema import RelicError
from reliclab.vault import LocalFileOps, Vault

from tests.support.resolve import composition
from tests.support.vault import asset


def test_complete_resolution_and_lock_update_demo(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    for document in (
        asset(id="base", constraints=["Preserve intent"]),
        asset(id="editor", extends="base@1", body="Review the draft."),
        asset("skill", id="review"),
        asset("skill", id="summarize"),
        asset("memory", id="notes"),
    ):
        vault.create(document)
    request = composition(persona="editor", skills=["review@1", "summarize"], memory=["notes"])
    frozen = vault.snapshot()
    original = resolve(request, frozen)
    stored_lock = CompositionLock.from_json(original.lock.to_json())
    vault.create(asset("skill", id="review", version="1.1.0", body="New review rules"))
    refreshed = vault.snapshot()
    assert resolve(request, frozen) == original
    assert resolve(request, refreshed, lock=stored_lock) == original
    updated = resolve(request, refreshed)
    assert updated.skills[0].key.version == "1.1.0"
    assert updated.lock.digest != original.lock.digest
    assert updated.persona is not None
    assert updated.persona.constraints == ("Preserve intent",)


@pytest.mark.parametrize("mutation", ["content", "comment", "delete"])
def test_locked_source_changes_are_detected_from_fresh_snapshot(
    tmp_path: Path, mutation: str
) -> None:
    vault = Vault(tmp_path)
    original = vault.create(asset("skill"))
    request = composition(skills=["sample"])
    source = vault.snapshot()
    lock = resolve(request, source).lock
    path = tmp_path / original.relative_path
    if mutation == "content":
        vault.update(original.key, asset("skill", body="Changed"), original.content_hash)
    elif mutation == "comment":
        path.write_bytes(original.content.replace(b"---\n", b"---\n# Changed comment\n", 1))
    else:
        vault.delete(original.key, original.content_hash)
    assert resolve(request, source, lock=lock).lock == lock
    with pytest.raises(ResolutionError) as caught:
        resolve(request, vault.snapshot(), lock=lock)
    assert caught.value.code == "SOURCE_CHANGED"


def test_path_rename_does_not_break_portable_lock(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    original = vault.create(asset("skill"))
    request = composition(skills=["sample"])
    lock = resolve(request, vault.snapshot()).lock
    (tmp_path / original.relative_path).rename(tmp_path / "skills/renamed.md")
    assert resolve(request, vault.snapshot(), lock=lock).lock == lock


class ChangingScan(LocalFileOps):
    scans: int = 0

    def entries(self, directory: str) -> tuple[str, ...]:
        if directory == "personas":
            self.scans += 1
            if self.scans == 2:
                path = self.root / "personas/sample@1.0.0.md"
                path.write_bytes(path.read_bytes().replace(b"---\n", b"---\n# changed\n", 1))
        return super().entries(directory)


def test_two_pass_capture_rejects_external_catalog_change(tmp_path: Path) -> None:
    Vault(tmp_path).create(asset())
    with pytest.raises(RelicError) as caught:
        Vault(tmp_path, file_ops=ChangingScan(tmp_path)).snapshot()
    assert caught.value.code == "SOURCE_CHANGED"


def test_empty_vault_snapshot(tmp_path: Path) -> None:
    assert Vault(tmp_path).snapshot().modules == ()


class ReverseScan(LocalFileOps):
    def entries(self, directory: str) -> tuple[str, ...]:
        return tuple(reversed(super().entries(directory)))


def test_real_directory_enumeration_order_cannot_change_lock(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    for version in ("1.0.0", "1.9.0", "1.10.0"):
        vault.create(asset("skill", version=version))
    request = composition(skills=["sample@1"])
    expected = resolve(request, vault.snapshot())
    reversed_vault = Vault(tmp_path, file_ops=ReverseScan(tmp_path))
    assert resolve(request, reversed_vault.snapshot()).lock.to_json() == expected.lock.to_json()
