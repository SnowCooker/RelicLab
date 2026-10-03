"""Provider-independent, provenance-preserving composition IR."""

from .budget import TokenCounter, Utf8ByteCounter
from .engine import compose
from .types import (
    BlockTokenCount,
    BudgetOmission,
    BudgetReport,
    ComposedContext,
    ComposedTool,
    ComposeLimits,
    ComposeRequest,
    CompositionManifest,
    ContextBlock,
    ContextData,
    ModuleSource,
    TokenCount,
    ToolTokenCount,
)

__all__ = [
    "BlockTokenCount",
    "BudgetOmission",
    "BudgetReport",
    "ComposedContext",
    "ComposedTool",
    "ComposeLimits",
    "ComposeRequest",
    "CompositionManifest",
    "ContextBlock",
    "ContextData",
    "ModuleSource",
    "TokenCount",
    "TokenCounter",
    "ToolTokenCount",
    "Utf8ByteCounter",
    "compose",
]
