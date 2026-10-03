"""Provider-independent, provenance-preserving composition IR."""

from .engine import compose
from .types import (
    BudgetReport,
    ComposedContext,
    ComposedTool,
    ComposeLimits,
    ComposeRequest,
    CompositionManifest,
    ContextBlock,
    ContextData,
    ModuleSource,
)

__all__ = [
    "BudgetReport",
    "ComposedContext",
    "ComposedTool",
    "ComposeLimits",
    "ComposeRequest",
    "CompositionManifest",
    "ContextBlock",
    "ContextData",
    "ModuleSource",
    "compose",
]
