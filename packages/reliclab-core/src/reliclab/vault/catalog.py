"""Validated immutable content catalogs, independent of later filesystem changes."""

import hashlib
from dataclasses import dataclass

from reliclab.schema import ModuleKey, RelicError
from reliclab.schema.types import has_glob, relative_path

from .types import DIRECTORIES, ModuleSnapshot


@dataclass(frozen=True)
class CatalogSnapshot:
    modules: tuple[ModuleSnapshot, ...]

    def __post_init__(self) -> None:
        modules = tuple(self.modules)
        keys: set[ModuleKey] = set()
        paths: set[str] = set()
        for item in modules:
            if not isinstance(item.content, bytes):
                raise RelicError("SCHEMA_INVALID", "Catalog content must be immutable bytes.")
            try:
                ModuleKey.model_validate(item.key)
            except ValueError:
                raise RelicError(
                    "SCHEMA_INVALID", "Catalog keys must be validated module keys."
                ) from None
            try:
                item.relative_path.encode("utf-8")
                relative_path(item.relative_path)
            except ValueError:
                raise RelicError(
                    "PATH_DENIED", "Catalog paths must be portable and relative."
                ) from None
            parts = item.relative_path.split("/")
            if (
                len(parts) != 2
                or parts[0] != DIRECTORIES[item.key.kind]
                or not parts[1].lower().endswith(".md")
                or has_glob(item.relative_path)
            ):
                raise RelicError("PATH_DENIED", "Catalog paths must identify flat module files.")
            if (
                item.document.key != item.key
                or hashlib.sha256(item.content).hexdigest() != item.content_hash
            ):
                raise RelicError(
                    "SOURCE_CHANGED", "Catalog identity or content hash is inconsistent."
                )
            if item.key in keys or item.relative_path.casefold() in paths:
                raise RelicError("VERSION_CONFLICT", "Catalog contains duplicate keys or paths.")
            keys.add(item.key)
            paths.add(item.relative_path.casefold())
        object.__setattr__(
            self,
            "modules",
            tuple(sorted(modules, key=lambda item: (item.key.kind, item.key.id, item.key.version))),
        )
