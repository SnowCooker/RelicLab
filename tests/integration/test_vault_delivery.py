"""Real filesystem, process competition, commit boundaries, and recovery checks."""

import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from reliclab.codec import serialize_module
from reliclab.schema import RelicError
from reliclab.vault import CommitReceipt, LocalFileOps, PostCommitError, Vault

from tests.support.vault import asset


def competing_update(root: str, digest: str, barrier: Any, output: Any, label: str) -> None:
    try:
        vault = Vault(root)
        barrier.wait(timeout=20)
        result = vault.update(asset().key, asset(name=label), digest)
        output.put(("ok", result.document.name))
    except RelicError as error:
        output.put((error.code, label))


@pytest.mark.integration
def test_cross_process_updates_have_one_winner(tmp_path: Path) -> None:
    initial = Vault(tmp_path).create(asset())
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    output = context.Queue()
    processes = [
        context.Process(
            target=competing_update,
            args=(str(tmp_path), initial.content_hash, barrier, output, label),
        )
        for label in ("First", "Second")
    ]
    try:
        for process in processes:
            process.start()
        barrier.wait(timeout=20)
        results = [output.get(timeout=30), output.get(timeout=30)]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert sorted(item[0] for item in results) == ["SOURCE_CHANGED", "ok"]
        winner = next(item[1] for item in results if item[0] == "ok")
        assert Vault(tmp_path).get(initial.key).document.name == winner
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
        output.close()
        output.join_thread()


@pytest.mark.integration
@pytest.mark.parametrize("operation", ["create", "update"])
def test_thread_competition_across_vault_instances(tmp_path: Path, operation: str) -> None:
    original = Vault(tmp_path).create(asset()) if operation == "update" else None
    barrier = Barrier(2)

    def worker(label: str) -> str:
        vault = Vault(tmp_path)
        barrier.wait(timeout=10)
        try:
            if original is None:
                vault.create(asset(name=label))
            else:
                vault.update(original.key, asset(name=label), original.content_hash)
            return "ok"
        except RelicError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ("First", "Second")))
    expected = "SOURCE_CHANGED" if original else "VERSION_CONFLICT"
    assert sorted(results) == [expected, "ok"]


class FaultOps(LocalFileOps):
    fault: str = ""
    stages: int = 0
    syncs: int = 0

    def stage(self, directory: str, content: bytes) -> str:
        self.stages += 1
        if self.fault == f"stage-{self.stages}":
            raise OSError("Injected disk write failure")
        result = super().stage(directory, content)
        if self.fault == "external" and self.stages == 2:
            (self.root / "personas/sample@1.0.0.md").write_bytes(
                serialize_module(asset(name="External editor")).encode()
            )
        if self.fault == "collision" and self.stages == 1:
            (self.root / "personas/sample@1.0.0.md").write_bytes(
                serialize_module(asset(name="External editor")).encode()
            )
        return result

    def publish(self, temporary: str, destination: str, *, replace: bool) -> None:
        if self.fault == "replace" and replace:
            raise OSError("Injected replacement failure")
        if self.fault == "backup" and destination.endswith(".bak"):
            raise OSError("Injected backup failure")
        super().publish(temporary, destination, replace=replace)

    def remove(self, relative: str, *, missing_ok: bool = False) -> None:
        if self.fault == "delete" and relative.endswith(".md"):
            raise OSError("Injected delete failure")
        if self.fault == "cleanup" and missing_ok and self.stages == 2:
            raise OSError("Injected cleanup failure")
        super().remove(relative, missing_ok=missing_ok)

    def sync(self, directory: str) -> bool:
        self.syncs += 1
        if self.fault == f"sync-{self.syncs}":
            raise OSError("Injected directory sync failure")
        return super().sync(directory)


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["stage-1", "stage-2", "backup", "replace", "sync-1"])
def test_precommit_disk_failures_preserve_original(tmp_path: Path, fault: str) -> None:
    original = Vault(tmp_path).create(asset())
    ops = FaultOps(tmp_path)
    ops.fault = fault
    with pytest.raises(RelicError) as caught:
        Vault(tmp_path, file_ops=ops).update(original.key, asset(name="New"), original.content_hash)
    assert not isinstance(caught.value, PostCommitError)
    assert caught.value.code == "IO_ERROR"
    assert Vault(tmp_path).get(original.key).content == original.content
    assert list(tmp_path.glob("*/.reliclab-tmp-*")) == []


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["sync-2", "cleanup"])
def test_postcommit_io_errors_have_unambiguous_receipts(tmp_path: Path, fault: str) -> None:
    original = Vault(tmp_path).create(asset())
    ops = FaultOps(tmp_path)
    ops.fault = fault
    with pytest.raises(PostCommitError) as caught:
        Vault(tmp_path, file_ops=ops).update(original.key, asset(name="New"), original.content_hash)
    assert caught.value.committed
    assert not caught.value.retryable
    assert caught.value.receipt.operation == "update"
    assert caught.value.receipt.backup_path is not None
    assert Vault(tmp_path).get(original.key).document.name == "New"
    assert (tmp_path / caught.value.receipt.backup_path).read_bytes() == original.content


@pytest.mark.integration
def test_external_edit_during_preparation_wins_over_stale_update(tmp_path: Path) -> None:
    original = Vault(tmp_path).create(asset())
    ops = FaultOps(tmp_path)
    ops.fault = "external"
    with pytest.raises(RelicError) as caught:
        Vault(tmp_path, file_ops=ops).update(original.key, asset(name="New"), original.content_hash)
    assert caught.value.code == "SOURCE_CHANGED"
    assert Vault(tmp_path).get(original.key).document.name == "External editor"
    assert next(tmp_path.glob("*/.reliclab-backup-*")).read_bytes() == original.content
    assert list(tmp_path.glob("*/.reliclab-tmp-*")) == []


@pytest.mark.integration
def test_atomic_create_never_overwrites_racing_destination(tmp_path: Path) -> None:
    ops = FaultOps(tmp_path)
    ops.fault = "collision"
    with pytest.raises(RelicError) as caught:
        Vault(tmp_path, file_ops=ops).create(asset())
    assert caught.value.code == "VERSION_CONFLICT"
    assert Vault(tmp_path).get(asset().key).document.name == "External editor"
    assert list(tmp_path.glob("*/.reliclab-tmp-*")) == []


@pytest.mark.integration
def test_delete_failure_retains_original_and_recovery_backup(tmp_path: Path) -> None:
    original = Vault(tmp_path).create(asset())
    ops = FaultOps(tmp_path)
    ops.fault = "delete"
    with pytest.raises(RelicError) as caught:
        Vault(tmp_path, file_ops=ops).delete(original.key, original.content_hash)
    assert not isinstance(caught.value, PostCommitError)
    assert Vault(tmp_path).get(original.key).content == original.content
    assert next(tmp_path.glob("*/.reliclab-backup-*")).read_bytes() == original.content


@pytest.mark.integration
@pytest.mark.parametrize("operation", ["create", "update", "delete", "restore"])
def test_notification_failure_does_not_undo_or_repeat_commit(
    tmp_path: Path, operation: str
) -> None:
    vault = Vault(tmp_path)
    original = vault.create(asset())
    vault.delete(original.key, original.content_hash)
    backup = next(tmp_path.glob("*/.reliclab-backup-*")).relative_to(tmp_path).as_posix()
    if operation in ("update", "delete"):
        original = vault.create(asset())
    calls = []

    def notify(receipt: CommitReceipt) -> None:
        calls.append(receipt)
        raise RuntimeError("Injected notification failure")

    vault.on_change = notify
    with pytest.raises(PostCommitError) as caught:
        if operation == "create":
            vault.create(asset())
        elif operation == "update":
            vault.update(original.key, asset(name="Updated"), original.content_hash)
        elif operation == "delete":
            vault.delete(original.key, original.content_hash)
        else:
            vault.restore(backup)
    assert len(calls) == 1
    assert caught.value.receipt == calls[0]
    assert caught.value.receipt.operation == operation
    vault.on_change = None
    if operation == "delete":
        assert vault.list() == ()
    else:
        assert vault.get(original.key).content_hash == caught.value.receipt.content_hash


@pytest.mark.integration
def test_callbacks_run_after_unlock_and_can_refresh_catalog(tmp_path: Path) -> None:
    receipts = []
    reader = Vault(tmp_path, file_ops=LocalFileOps(tmp_path, lock_timeout=0))
    vault = Vault(tmp_path, on_change=lambda receipt: receipts.append((receipt, reader.list())))
    created = vault.create(asset())
    assert receipts[0][1][0].content_hash == created.content_hash


def test_restore_preserves_original_comments_and_crlf_bytes(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    raw = serialize_module(asset()).replace("---\n", "---\n# Keep this comment\n", 1)
    content = raw.replace("\n", "\r\n").encode()
    (tmp_path / "personas/handwritten.md").write_bytes(content)
    original = vault.get(asset().key)
    updated = vault.update(original.key, asset(name="Changed"), original.content_hash)
    backup = next(tmp_path.glob("*/.reliclab-backup-*")).relative_to(tmp_path).as_posix()
    restored = vault.restore(backup, updated.content_hash)
    assert restored.content == content
    assert (tmp_path / restored.relative_path).read_bytes() == content
    assert restored.relative_path == "personas/handwritten.md"
