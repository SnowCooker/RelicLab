"""In-memory catalogs exercise the production codec without filesystem coupling."""

import hashlib
from typing import Any

from reliclab.codec import parse_module, serialize_module
from reliclab.schema import Composition, ModuleDocument
from reliclab.vault import CatalogSnapshot, ModuleSnapshot
from reliclab.vault.types import DIRECTORIES

from tests.support.vault import asset


def composition(**modules: Any) -> Composition:
    document = asset("composition", id="workflow", modules=modules)
    assert isinstance(document, Composition)
    return document


def snapshot(document: ModuleDocument, path: str | None = None) -> ModuleSnapshot:
    content = serialize_module(document).encode("utf-8")
    parsed = parse_module(content)
    return ModuleSnapshot(
        parsed.key,
        path or f"{DIRECTORIES[parsed.kind]}/{parsed.id}@{parsed.version}.md",
        hashlib.sha256(content).hexdigest(),
        content,
    )


def catalog(*documents: ModuleDocument) -> CatalogSnapshot:
    return CatalogSnapshot(tuple(snapshot(document) for document in documents))
