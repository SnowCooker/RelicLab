"""Host-managed plain-text asset storage and recovery."""

from .files import FileOps, LocalFileOps
from .store import Vault
from .types import CommitReceipt, ModuleQuery, ModuleSnapshot, ModuleSummary, PostCommitError

__all__ = [
    "CommitReceipt",
    "FileOps",
    "LocalFileOps",
    "ModuleQuery",
    "ModuleSnapshot",
    "ModuleSummary",
    "PostCommitError",
    "Vault",
]
