"""Filesystem boundary and fault tests; all targets belong to test-owned roots."""

import os
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from filelock import SoftFileLock
from reliclab.schema import RelicError
from reliclab.vault import LocalFileOps, Vault, files

from tests.support.vault import asset


def directory_link(path: Path, target: Path) -> None:
    if os.name == "nt":
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "New-Item -ItemType Junction -Path $env:RELIC_TEST_LINK "
                "-Target $env:RELIC_TEST_TARGET",
            ],
            env={**os.environ, "RELIC_TEST_LINK": str(path), "RELIC_TEST_TARGET": str(target)},
            check=True,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        path.symlink_to(target, target_is_directory=True)


def unlink_directory_link(path: Path) -> None:
    if os.name == "nt":
        path.rmdir()
    else:
        path.unlink()


@pytest.mark.security
@pytest.mark.parametrize(
    "relative",
    [
        "../outside",
        "/absolute",
        "C:/absolute",
        "C:relative",
        "//server/share",
        "\\\\server\\share",
        "personas/../x",
        "personas\\x.md",
        "personas/file:stream",
        "personas/con",
        "personas/aux.txt",
        "personas/COM1.md",
        "personas/NUL",
        "personas/a.",
        "personas/a ",
        "personas/\x00.md",
        "personas/\ud800.md",
        "personas/*.md",
        "personas/a?.md",
        "personas/[ab].md",
        ".git/config",
        ".env",
        ".ssh/key",
        ".aws/credentials",
        ".codex/auth.json",
    ],
)
def test_untrusted_paths_never_reach_open(
    tmp_path: Path, relative: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = LocalFileOps(tmp_path)
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: pytest.fail("Unsafe open"))
    with pytest.raises(RelicError) as caught:
        ops.read(relative, 100)
    assert caught.value.code == "PATH_DENIED"


@pytest.mark.parametrize("root", ["../outside", "C:relative", "//server/share", "\\\\?\\C:\\data"])
def test_unsafe_root_spellings_rejected(root: str) -> None:
    with pytest.raises(RelicError) as caught:
        LocalFileOps(root)
    assert caught.value.code == "PATH_DENIED"


def test_reserved_root_and_non_directory_components(tmp_path: Path) -> None:
    with pytest.raises(RelicError):
        LocalFileOps(tmp_path / "con")
    (tmp_path / "file").write_bytes(b"original")
    with pytest.raises(RelicError):
        LocalFileOps(tmp_path / "file")
    with pytest.raises(RelicError):
        LocalFileOps(tmp_path / "file" / "child")


def test_non_utf8_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RelicError) as caught:
        LocalFileOps(tmp_path / "\ud800")
    assert caught.value.code == "PATH_DENIED"


@pytest.mark.parametrize("name", [".git", ".env", ".ssh", ".aws", ".codex"])
def test_protected_root_is_rejected_without_creation(tmp_path: Path, name: str) -> None:
    with pytest.raises(RelicError) as caught:
        LocalFileOps(tmp_path / name)
    assert caught.value.code == "PATH_DENIED"
    assert not (tmp_path / name).exists()


@pytest.mark.security
@pytest.mark.parametrize("linked", ["root", "kind", "entry"])
def test_symlink_or_windows_junction_is_rejected(tmp_path: Path, linked: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "private.txt"
    marker.write_bytes(b"fixture-private-value")
    root = tmp_path / "vault"
    ops = LocalFileOps(root)
    if linked == "root":
        link = tmp_path / "linked-root"
    elif linked == "kind":
        link = root / "personas"
        link.rmdir()
    else:
        link = root / "personas/linked.md"
    directory_link(link, outside)
    try:
        with pytest.raises(RelicError) as caught:
            if linked == "root":
                LocalFileOps(link)
            else:
                Vault(root, file_ops=ops).list()
        assert caught.value.code == "PATH_DENIED"
        assert marker.read_bytes() == b"fixture-private-value"
    finally:
        unlink_directory_link(link)


@pytest.mark.security
def test_external_hardlink_is_rejected_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    ops = LocalFileOps(root)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"fixture-private-value")
    os.link(outside, root / "personas/linked.md")
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: pytest.fail("Hardlink was opened"))
    with pytest.raises(RelicError) as caught:
        ops.read("personas/linked.md", 100)
    assert caught.value.code == "PATH_DENIED"


@pytest.mark.security
def test_replaced_parent_link_is_detected_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    ops = LocalFileOps(root)
    original = Vault(root, file_ops=ops).create(asset())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sample@1.0.0.md").write_bytes(b"fixture-private-value")
    real_open, real_fdopen = os.open, os.fdopen
    parent = root / "personas"
    moved = root / "saved-personas"
    reads: list[bool] = []

    def swap(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        parent.rename(moved)
        directory_link(parent, outside)
        return real_open(path, flags, *args, **kwargs)

    @contextmanager
    def track(descriptor: int, mode: str) -> Iterator[Any]:
        with real_fdopen(descriptor, mode) as stream:

            class Reader:
                def fileno(self) -> int:
                    return stream.fileno()

                def read(self, limit: int) -> bytes:
                    reads.append(True)
                    return cast(bytes, stream.read(limit))

            yield Reader()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", swap)
            patch.setattr(os, "fdopen", track)
            with pytest.raises(RelicError) as caught:
                ops.read(original.relative_path, 1000)
        assert caught.value.code == "PATH_DENIED"
        assert reads == []
    finally:
        if moved.exists():
            unlink_directory_link(parent)
            moved.rename(parent)


def test_regular_file_swap_between_stat_and_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = LocalFileOps(tmp_path)
    snapshot = Vault(tmp_path, file_ops=ops).create(asset())
    real_open = os.open
    original = tmp_path / snapshot.relative_path

    def swap(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        original.rename(original.with_suffix(".old"))
        original.write_bytes(b"replacement")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap)
    with pytest.raises(RelicError) as caught:
        ops.read(snapshot.relative_path, 1000)
    assert caught.value.code == "SOURCE_CHANGED"


def test_in_place_write_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = LocalFileOps(tmp_path)
    snapshot = Vault(tmp_path, file_ops=ops).create(asset())
    real_fdopen = os.fdopen

    @contextmanager
    def mutate(descriptor: int, mode: str) -> Iterator[Any]:
        with real_fdopen(descriptor, mode) as stream:

            class Reader:
                def fileno(self) -> int:
                    return stream.fileno()

                def read(self, limit: int) -> bytes:
                    content = stream.read(limit)
                    (tmp_path / snapshot.relative_path).write_bytes(b"external")
                    return cast(bytes, content)

            yield Reader()

    monkeypatch.setattr(os, "fdopen", mutate)
    with pytest.raises(RelicError) as caught:
        ops.read(snapshot.relative_path, 1000)
    assert caught.value.code == "SOURCE_CHANGED"


@pytest.mark.parametrize("fault", ["write", "fsync"])
def test_failed_temporary_write_removes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    ops = LocalFileOps(tmp_path)
    real_fdopen = os.fdopen

    @contextmanager
    def broken(descriptor: int, mode: str) -> Iterator[Any]:
        with real_fdopen(descriptor, mode) as stream:

            class Writer:
                def write(self, content: bytes) -> None:
                    stream.write(content[:3])
                    raise OSError("Injected partial write")

            yield Writer()

    def fail_sync(descriptor: int) -> None:
        raise OSError("Injected fsync failure")

    with monkeypatch.context() as patch:
        if fault == "write":
            patch.setattr(os, "fdopen", broken)
        else:
            patch.setattr(os, "fsync", fail_sync)
        with pytest.raises(OSError):
            ops.stage("personas", b"partial content")
    assert ops.entries("personas") == ()


def test_directory_sync_capability_and_descriptor_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = LocalFileOps(tmp_path)
    monkeypatch.setattr(files, "DIRECTORY_FSYNC", False)
    assert ops.sync("personas") is False
    closed: list[int] = []
    monkeypatch.setattr(files, "DIRECTORY_FSYNC", True)
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda *args, **kwargs: 123)
        patch.setattr(os, "close", closed.append)
        patch.setattr(os, "fsync", lambda descriptor: None)
        assert ops.sync("personas") is True
    assert closed == [123]


def test_lock_timeout_and_soft_fallback_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = LocalFileOps(tmp_path, lock_timeout=0)
    with ops.locked(), pytest.raises(RelicError) as caught, ops.locked():
        pytest.fail("Second physical lock should not be acquired")
    assert caught.value.retryable
    monkeypatch.setattr(files, "FileLock", SoftFileLock)
    with pytest.raises(RelicError, match="native"), ops.locked():
        pytest.fail("Soft locks must not be used")


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_read_limit_is_strict(tmp_path: Path, value: Any) -> None:
    with pytest.raises(ValueError):
        LocalFileOps(tmp_path).read("personas/missing.md", value)


@pytest.mark.parametrize(
    "options",
    [
        {"lock_timeout": -1},
        {"lock_timeout": float("inf")},
        {"lock_timeout": float("nan")},
        {"lock_timeout": True},
        {"lock_timeout": "5"},
        {"max_entries": 0},
        {"max_entries": True},
    ],
)
def test_fileops_configuration_validation(tmp_path: Path, options: Any) -> None:
    with pytest.raises(ValueError):
        LocalFileOps(tmp_path, **options)


def test_read_size_directory_and_entry_limit(tmp_path: Path) -> None:
    ops = LocalFileOps(tmp_path, max_entries=1)
    (tmp_path / "personas/one.md").write_bytes(b"123")
    assert ops.read("personas/one.md", 3) == b"123"
    with pytest.raises(RelicError, match="bounded"):
        ops.read("personas/one.md", 2)
    with pytest.raises(RelicError):
        ops.read("personas", 10)
    (tmp_path / "personas/two.md").write_bytes(b"2")
    with pytest.raises(RelicError, match="entry limit"):
        ops.entries("personas")
    (tmp_path / "skills/nested").mkdir()
    with pytest.raises(RelicError):
        ops.entries("skills")
    with pytest.raises(FileNotFoundError):
        ops.read("missing/file.md", 10)


def test_cross_directory_publication_is_denied(tmp_path: Path) -> None:
    ops = LocalFileOps(tmp_path)
    temporary = ops.stage("personas", b"test")
    with pytest.raises(RelicError):
        ops.publish(temporary, "skills/test.md", replace=False)
    ops.remove(temporary)


def test_nonregular_entry_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(st_mode=stat.S_IFIFO, st_file_attributes=0)
    monkeypatch.setattr(Path, "lstat", lambda self: fake)
    with pytest.raises(RelicError):
        files.inspect_entry(tmp_path / "pipe")
