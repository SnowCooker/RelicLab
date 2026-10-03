"""Immutable storage receipts and validated catalog queries."""

from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import Field

from reliclab.codec import CodecLimits, parse_module
from reliclab.schema import ModuleDocument, ModuleId, ModuleKey, RelicError
from reliclab.schema.models import Kind, StrictModel, Strings

DIRECTORIES: dict[Kind, str] = {
    "persona": "personas",
    "skill": "skills",
    "memory": "memory",
    "composition": "compositions",
}
Operation = Literal["create", "update", "delete", "restore"]


class ModuleQuery(StrictModel):
    kind: Kind | None = None
    id: ModuleId | None = None
    text: Annotated[str, Field(max_length=200)] = ""
    tags: Strings = ()
    offset: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1, le=1000)] = 100


class ModuleSummary(StrictModel):
    key: ModuleKey
    name: str
    description: str
    tags: tuple[str, ...]
    relative_path: str
    content_hash: str


@dataclass(frozen=True)
class ModuleSnapshot:
    key: ModuleKey
    relative_path: str
    content_hash: str
    content: bytes = field(repr=False)
    limits: CodecLimits = field(default_factory=CodecLimits, repr=False)

    @property
    def document(self) -> ModuleDocument:
        """Return a fresh DTO so mutable mappings cannot corrupt the byte snapshot."""
        return parse_module(self.content, self.relative_path, limits=self.limits)


@dataclass(frozen=True)
class CommitReceipt:
    operation: Operation
    key: ModuleKey
    content_hash: str | None
    backup_path: str | None


class PostCommitError(RelicError):
    """The mutation committed; inspect the receipt and reload, never blindly retry."""

    def __init__(self, receipt: CommitReceipt) -> None:
        super().__init__(
            "IO_ERROR", "Asset committed, but finalization failed; reload before any retry."
        )
        self.committed = True
        self.receipt = receipt
