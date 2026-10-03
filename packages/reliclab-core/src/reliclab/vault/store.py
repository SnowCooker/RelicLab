"""Database-free catalog scans, compare-before-write mutations, and recovery."""

import hashlib
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from reliclab.codec import CodecLimits, parse_module, serialize_module
from reliclab.schema import (
    Composition,
    ModuleDocument,
    ModuleKey,
    Persona,
    RelicError,
    validate_module,
)

from .catalog import CatalogSnapshot
from .files import FileOps, LocalFileOps
from .types import (
    DIRECTORIES,
    CommitReceipt,
    ModuleQuery,
    ModuleSnapshot,
    ModuleSummary,
    Operation,
    PostCommitError,
)

DEFAULT_LIMITS = CodecLimits()
DEFAULT_QUERY = ModuleQuery()
BACKUP = re.compile(r"^(personas|skills|memory|compositions)/\.reliclab-backup-[0-9a-f]{32}\.bak$")
HASH = re.compile(r"^[0-9a-f]{64}$")


class Vault:
    """A local, host-managed Vault shared by cooperating library clients."""

    def __init__(
        self,
        root: str | Path,
        *,
        file_ops: FileOps | None = None,
        limits: CodecLimits = DEFAULT_LIMITS,
        on_change: Callable[[CommitReceipt], None] | None = None,
        max_modules: int = 10000,
        max_catalog_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if any(type(value) is not int or value < 1 for value in (max_modules, max_catalog_bytes)):
            raise ValueError("Catalog limits must be positive integers")
        with self._errors():
            self.files = file_ops if file_ops is not None else LocalFileOps(root)
            if self.files.root != Path(root).absolute():
                raise ValueError("FileOps root must match the Vault root")
        self.limits = limits
        self.on_change = on_change
        self.max_modules = max_modules
        self.max_catalog_bytes = max_catalog_bytes

    def _capacity(self, count: int, size: int) -> None:
        if count > self.max_modules or size > self.max_catalog_bytes:
            raise RelicError("IO_ERROR", "Vault catalog exceeds its host-configured limits.")

    @contextmanager
    def _errors(self) -> Iterator[None]:
        try:
            yield
        except OSError:
            raise RelicError(
                "IO_ERROR", "Vault filesystem operation failed; reload and inspect recovery files."
            ) from None

    def _snapshot(self, path: str, content: bytes) -> ModuleSnapshot:
        document = parse_module(content, path, limits=self.limits)
        if path.split("/")[0] != DIRECTORIES[document.kind]:
            raise RelicError("SCHEMA_INVALID", "Asset kind does not match its directory.")
        return ModuleSnapshot(
            document.key, path, hashlib.sha256(content).hexdigest(), content, self.limits
        )

    def _read(self, path: str) -> ModuleSnapshot:
        maximum = self.limits.max_frontmatter_bytes + self.limits.max_body_bytes + 13
        return self._snapshot(path, self.files.read(path, maximum))

    def _scan(self) -> dict[ModuleKey, ModuleSnapshot]:
        catalog: dict[ModuleKey, ModuleSnapshot] = {}
        paths: set[str] = set()
        size = 0
        for directory in DIRECTORIES.values():
            for path in self.files.entries(directory):
                if not path.lower().endswith(".md"):
                    continue
                snapshot = self._read(path)
                size += len(snapshot.content)
                self._capacity(len(catalog) + 1, size)
                if snapshot.key in catalog or path.casefold() in paths:
                    raise RelicError(
                        "VERSION_CONFLICT", "Duplicate asset key or portable path in Vault."
                    )
                paths.add(path.casefold())
                catalog[snapshot.key] = snapshot
        return catalog

    @staticmethod
    def _key(key: ModuleKey) -> ModuleKey:
        return ModuleKey.model_validate(key)

    @staticmethod
    def _expected(expected_hash: str) -> None:
        if not isinstance(expected_hash, str) or not HASH.fullmatch(expected_hash):
            raise ValueError("expected_hash must be a lowercase SHA-256 hex digest")

    def get(self, key: ModuleKey) -> ModuleSnapshot:
        key = self._key(key)
        with self._errors(), self.files.locked():
            snapshot = self._scan().get(key)
            if snapshot is None:
                raise RelicError("NOT_FOUND", "Asset key was not found in Vault.")
            return snapshot

    def snapshot(self) -> CatalogSnapshot:
        """Capture bytes under one client lock and detect changes in a second scan."""
        with self._errors(), self.files.locked():
            first = self._scan()
            second = self._scan()
            if first != second:
                raise RelicError("SOURCE_CHANGED", "Catalog changed during capture; reload.")
            return CatalogSnapshot(tuple(first.values()))

    def list(self, query: ModuleQuery = DEFAULT_QUERY) -> tuple[ModuleSummary, ...]:
        query = ModuleQuery.model_validate(query)
        with self._errors(), self.files.locked():
            snapshots = self._scan().values()
            summaries = []
            for snapshot in snapshots:
                document = snapshot.document
                if query.kind is not None and document.kind != query.kind:
                    continue
                if query.id is not None and document.id != query.id:
                    continue
                if not set(query.tags).issubset(document.tags):
                    continue
                if (
                    query.text.casefold()
                    not in f"{document.id} {document.name} {document.description}".casefold()
                ):
                    continue
                summaries.append(
                    ModuleSummary(
                        key=snapshot.key,
                        name=document.name,
                        description=document.description,
                        tags=document.tags,
                        relative_path=snapshot.relative_path,
                        content_hash=snapshot.content_hash,
                    )
                )
            summaries.sort(key=lambda item: (item.key.kind, item.key.id, item.key.version))
            return tuple(summaries[query.offset : query.offset + query.limit])

    def create(self, document: ModuleDocument) -> ModuleSnapshot:
        document = validate_module(document, max_body_bytes=self.limits.max_body_bytes)
        result = self._mutate("create", document.key, document, None)
        assert result is not None
        return result

    def update(
        self, key: ModuleKey, document: ModuleDocument, expected_hash: str
    ) -> ModuleSnapshot:
        key = self._key(key)
        self._expected(expected_hash)
        document = validate_module(document, max_body_bytes=self.limits.max_body_bytes)
        if document.key != key:
            raise RelicError("SCHEMA_INVALID", "Update cannot change an asset key.")
        result = self._mutate("update", key, document, expected_hash)
        assert result is not None
        return result

    def delete(self, key: ModuleKey, expected_hash: str) -> None:
        self._expected(expected_hash)
        self._mutate("delete", self._key(key), None, expected_hash)

    def restore(self, backup_path: str, expected_hash: str | None = None) -> ModuleSnapshot:
        """Restore exact backup bytes; None means the original key must be absent."""
        if not BACKUP.fullmatch(backup_path):
            raise RelicError("PATH_DENIED", "Select a Vault recovery backup path.")
        if expected_hash is not None:
            self._expected(expected_hash)
        with self._errors(), self.files.locked():
            backup = self._read(backup_path)
        result = self._mutate(
            "restore", backup.key, backup.document, expected_hash, raw=backup.content
        )
        assert result is not None
        return result

    def _backup(self, snapshot: ModuleSnapshot) -> str:
        directory = snapshot.relative_path.split("/")[0]
        destination = f"{directory}/.reliclab-backup-{uuid4().hex}.bak"
        temporary = self.files.stage(directory, snapshot.content)
        try:
            self.files.publish(temporary, destination, replace=False)
        finally:
            self.files.remove(temporary, missing_ok=True)
        self.files.sync(directory)
        return destination

    def _referenced(self, key: ModuleKey, catalog: dict[ModuleKey, ModuleSnapshot]) -> None:
        for other_key, snapshot in catalog.items():
            if other_key == key:
                continue
            document = snapshot.document
            references: list[str] = []
            if isinstance(document, Persona) and key.kind == "persona" and document.extends:
                references.append(document.extends)
            if isinstance(document, Composition):
                if key.kind == "persona" and document.modules.persona:
                    references.append(document.modules.persona)
                elif key.kind == "skill":
                    references.extend(document.modules.skills)
                elif key.kind == "memory":
                    references.extend(document.modules.memory)
            if any(reference.partition("@")[0] == key.id for reference in references):
                raise RelicError(
                    "VERSION_CONFLICT", "Asset is referenced; remove references before deleting."
                )

    def _mutate(
        self,
        operation: Operation,
        key: ModuleKey,
        document: ModuleDocument | None,
        expected_hash: str | None,
        *,
        raw: bytes | None = None,
    ) -> ModuleSnapshot | None:
        receipt: CommitReceipt | None = None
        result: ModuleSnapshot | None = None
        backup_path = None
        try:
            with self.files.locked():
                catalog = self._scan()
                current = catalog.get(key)
                if expected_hash is None:
                    if current is not None:
                        raise RelicError(
                            "VERSION_CONFLICT", "Create or restore would overwrite an existing key."
                        )
                else:
                    if current is None:
                        raise RelicError("NOT_FOUND", "Asset key was not found in Vault.")
                    if current.content_hash != expected_hash:
                        raise RelicError(
                            "SOURCE_CHANGED",
                            "Asset revision changed; reload and merge before retrying.",
                        )
                if operation == "update" and current is not None and current.document == document:
                    return current
                if operation == "delete":
                    self._referenced(key, catalog)
                directory = DIRECTORIES[key.kind]
                destination = (
                    current.relative_path if current else f"{directory}/{key.id}@{key.version}.md"
                )
                if current is None and any(
                    item.relative_path.casefold() == destination.casefold()
                    for item in catalog.values()
                ):
                    raise RelicError(
                        "VERSION_CONFLICT", "Destination conflicts with a portable path."
                    )
                content = None
                if document is not None:
                    content = (
                        raw
                        if raw is not None
                        else serialize_module(document, limits=self.limits).encode("utf-8")
                    )
                    result = self._snapshot(destination, content)
                    self._capacity(
                        len(catalog) + (current is None),
                        sum(len(item.content) for item in catalog.values())
                        - (len(current.content) if current else 0)
                        + len(content),
                    )
                if current is not None:
                    backup_path = self._backup(current)
                temporary = self.files.stage(directory, content) if content is not None else None
                try:
                    if (
                        current is not None
                        and self._read(destination).content_hash != expected_hash
                    ):
                        raise RelicError(
                            "SOURCE_CHANGED", "Asset changed before commit; reload and merge."
                        )
                    if temporary is None:
                        self.files.remove(destination)
                    else:
                        try:
                            self.files.publish(temporary, destination, replace=current is not None)
                        except FileExistsError:
                            raise RelicError(
                                "VERSION_CONFLICT",
                                "Destination already exists; no asset was overwritten.",
                            ) from None
                    receipt = CommitReceipt(
                        operation, key, result.content_hash if result else None, backup_path
                    )
                finally:
                    if temporary is not None:
                        self.files.remove(temporary, missing_ok=True)
                self.files.sync(directory)
            if self.on_change is not None:
                self.on_change(receipt)
        except Exception as error:
            if receipt is not None:
                raise PostCommitError(receipt) from None
            if isinstance(error, OSError):
                raise RelicError(
                    "IO_ERROR",
                    "Vault mutation failed before commit; inspect recovery files and reload.",
                ) from None
            raise
        return result
