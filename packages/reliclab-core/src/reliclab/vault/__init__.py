"""Host-managed plain-text asset storage and recovery."""

from .catalog import CatalogSnapshot
from .files import FileOps, LocalFileOps
from .store import Vault
from .types import CommitReceipt, ModuleQuery, ModuleSnapshot, ModuleSummary, PostCommitError

__all__ = [
    "CatalogSnapshot",
    "CommitReceipt",
    "FileOps",
    "LocalFileOps",
    "ModuleQuery",
    "ModuleSnapshot",
    "ModuleSummary",
    "PostCommitError",
    "Vault",
]
