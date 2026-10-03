"""Local host-managed filesystem adapter, not an adversarial filesystem sandbox."""

import math
import os
import stat
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path, PureWindowsPath
from typing import Protocol
from uuid import uuid4

from filelock import FileLock, SoftFileLock, Timeout

from reliclab.schema import RelicError
from reliclab.schema.types import has_glob, relative_path

from .types import DIRECTORIES

DIRECTORY_FSYNC = os.name != "nt"
REPARSE_POINT = 0x400
PROTECTED_NAMES = {".git", ".env", ".ssh", ".aws", ".codex"}


class FileOps(Protocol):
    root: Path

    def locked(self) -> AbstractContextManager[None]: ...
    def entries(self, directory: str) -> tuple[str, ...]: ...
    def read(self, relative: str, limit: int) -> bytes: ...
    def stage(self, directory: str, content: bytes) -> str: ...
    def publish(self, temporary: str, destination: str, *, replace: bool) -> None: ...
    def remove(self, relative: str, *, missing_ok: bool = False) -> None: ...
    def sync(self, directory: str) -> bool: ...


def deny() -> None:
    raise RelicError("PATH_DENIED", "Vault path must be local, contained, and free of links.")


def inspect_entry(path: Path, *, allow_hardlink: bool = False) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
        deny()
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        deny()
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1 and not allow_hardlink:
        deny()
    return info


class LocalFileOps:
    """Reject static links and detect ordinary races; use a trusted local root."""

    def __init__(self, root: str | Path, *, lock_timeout: float = 5, max_entries: int = 20000):
        raw = str(root)
        windows = PureWindowsPath(raw)
        if (
            raw.startswith(("//", "\\\\"))
            or ".." in Path(raw).parts
            or (windows.drive and not windows.is_absolute())
            or (os.name != "nt" and windows.drive)
        ):
            deny()
        if (
            type(lock_timeout) not in (int, float)
            or not math.isfinite(lock_timeout)
            or lock_timeout < 0
            or type(max_entries) is not int
            or max_entries < 1
        ):
            raise ValueError("Use a nonnegative lock timeout and positive entry limit")
        self.root = Path(root).absolute()
        if any(part.casefold() in PROTECTED_NAMES for part in self.root.parts):
            deny()
        try:
            str(self.root).encode("utf-8")
            relative_path("/".join(self.root.parts[1:]))
        except ValueError:
            deny()
        self.lock_timeout = lock_timeout
        self.max_entries = max_entries
        self._walk(self.root, create=True)
        for directory in DIRECTORIES.values():
            self._walk(self.root / directory, create=True)

    def _walk(
        self,
        path: Path,
        *,
        create: bool = False,
        missing_leaf: bool = False,
        allow_hardlink: bool = False,
    ) -> None:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            try:
                info = inspect_entry(current, allow_hardlink=allow_hardlink and current == path)
            except FileNotFoundError:
                if create:
                    try:
                        current.mkdir()
                    except FileExistsError:
                        pass
                    info = inspect_entry(current)
                elif missing_leaf and current == path:
                    return
                else:
                    raise
            if current != path and not stat.S_ISDIR(info.st_mode):
                deny()
            if create and not stat.S_ISDIR(info.st_mode):
                deny()

    def _checked(
        self, relative: str, *, missing_leaf: bool = False, allow_hardlink: bool = False
    ) -> Path:
        try:
            relative.encode("utf-8")
            relative_path(relative)
        except ValueError:
            deny()
        if has_glob(relative) or any(
            part.casefold() in PROTECTED_NAMES for part in relative.split("/")
        ):
            deny()
        path = self.root.joinpath(*relative.split("/"))
        if not path.is_relative_to(self.root):
            deny()
        self._walk(path, missing_leaf=missing_leaf, allow_hardlink=allow_hardlink)
        return path

    @contextmanager
    def locked(self) -> Iterator[None]:
        path = self._checked(".reliclab.lock", missing_leaf=True)
        if issubclass(FileLock, SoftFileLock):
            raise RelicError("IO_ERROR", "A native filesystem lock is required.")
        lock = FileLock(
            path,
            timeout=self.lock_timeout,
            mode=0o600,
            fallback_to_soft=False,
            preserve_lock_file=True,
            close_error_policy="raise",
        )
        try:
            with lock:
                self._checked(".reliclab.lock")
                yield
        except Timeout:
            raise RelicError(
                "IO_ERROR", "Vault is busy; retry after reloading.", retryable=True
            ) from None

    def entries(self, directory: str) -> tuple[str, ...]:
        path = self._checked(directory)
        result: list[str] = []
        with os.scandir(path) as entries:
            for entry in entries:
                if len(result) >= self.max_entries:
                    raise RelicError("IO_ERROR", "Vault directory exceeds the entry limit.")
                relative = f"{directory}/{entry.name}"
                checked = self._checked(relative)
                if stat.S_ISDIR(checked.lstat().st_mode):
                    deny()
                result.append(relative)
        return tuple(sorted(result))

    def read(self, relative: str, limit: int) -> bytes:
        if type(limit) is not int or limit < 1:
            raise ValueError("Read limit must be a positive byte count")
        path = self._checked(relative)
        before = inspect_entry(path)
        if not stat.S_ISREG(before.st_mode):
            deny()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            self._checked(relative)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise RelicError("SOURCE_CHANGED", "Asset changed while opening; reload.")
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                deny()
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        latest = inspect_entry(self._checked(relative))

        def stamp(item: os.stat_result) -> tuple[int, int, int, int]:
            return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns

        # Windows path stat and handle stat can expose different ctime meanings.
        if (
            stamp(before) != stamp(after)
            or stamp(after) != stamp(latest)
            or before.st_ctime_ns != latest.st_ctime_ns
            or opened.st_ctime_ns != after.st_ctime_ns
        ):
            raise RelicError("SOURCE_CHANGED", "Asset changed while reading; reload.")
        if len(data) > limit:
            raise RelicError("PARSE_ERROR", "Asset exceeds the bounded read limit.")
        return data

    def stage(self, directory: str, content: bytes) -> str:
        relative = f"{directory}/.reliclab-tmp-{uuid4().hex}.tmp"
        path = self._checked(relative, missing_leaf=True)
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                self._checked(relative)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            self.remove(relative, missing_ok=True)
            raise
        return relative

    def publish(self, temporary: str, destination: str, *, replace: bool) -> None:
        source = self._checked(temporary)
        target = self._checked(destination, missing_leaf=True)
        if source.parent != target.parent:
            deny()
        if replace:
            os.replace(source, target)
        else:
            os.link(source, target, follow_symlinks=False)

    def remove(self, relative: str, *, missing_ok: bool = False) -> None:
        name = relative.rsplit("/", 1)[-1]
        temporary = missing_ok and name.startswith(".reliclab-tmp-") and name.endswith(".tmp")
        self._checked(relative, missing_leaf=missing_ok, allow_hardlink=temporary).unlink(
            missing_ok=missing_ok
        )

    def sync(self, directory: str) -> bool:
        path = self._checked(directory)
        if not DIRECTORY_FSYNC:
            return False
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True
