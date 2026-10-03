"""Additive Core-content accounting and whole-block optional Memory removal."""

from dataclasses import dataclass
from typing import Protocol

from reliclab.resolve.types import canonical_json
from reliclab.schema import Diagnostic, RelicError

from .types import (
    BlockTokenCount,
    BudgetOmission,
    BudgetReport,
    ComposedTool,
    ContextBlock,
    ModuleSource,
    TokenCount,
    ToolTokenCount,
)


class TokenCounter(Protocol):
    """Trusted host adapter: deterministic, side-effect-free, versioned counting."""

    @property
    def counter_id(self) -> str: ...

    def count(self, text: str) -> TokenCount: ...


@dataclass(frozen=True)
class Utf8ByteCounter:
    """One unit per UTF-8 byte: an estimate, never a model-token guarantee."""

    @property
    def counter_id(self) -> str:
        return "utf8-bytes-v1"

    def count(self, text: str) -> TokenCount:
        return TokenCount(value=len(text.encode("utf-8")), exact=False, counter_id=self.counter_id)


DEFAULT_COUNTER = Utf8ByteCounter()


@dataclass(frozen=True)
class BudgetDecision:
    blocks: tuple[ContextBlock, ...]
    report: BudgetReport
    diagnostics: tuple[Diagnostic, ...]


def evaluate_budget(
    blocks: tuple[ContextBlock, ...],
    tools: tuple[ComposedTool, ...],
    *,
    token_budget: int,
    counter_id: str,
    counter: TokenCounter,
) -> BudgetDecision:
    """Measure each candidate once, retaining all tools and required content."""
    try:
        if counter.counter_id != counter_id:
            raise ValueError("Counter identity mismatch")
    except Exception:
        raise RelicError(
            "SCHEMA_INVALID", "The requested token counter is unavailable or mismatched."
        ) from None

    def measure(text: str) -> TokenCount:
        try:
            result = counter.count(text)
            if not isinstance(result, TokenCount):
                raise ValueError("Invalid counter result")
            result = TokenCount.model_validate(result)
            if result.counter_id != counter_id or counter.counter_id != counter_id:
                raise ValueError("Counter identity changed")
            return result
        except Exception:
            raise RelicError(
                "SCHEMA_INVALID", "Token counter failed or returned an invalid measurement."
            ) from None

    block_counts = tuple(
        BlockTokenCount(block_id=block.block_id, required=block.required, count=measure(block.text))
        for block in blocks
    )
    tool_counts = tuple(
        ToolTokenCount(
            name=tool.requirement.name,
            count=measure(canonical_json(tool.requirement.model_dump(mode="json"))),
        )
        for tool in tools
    )
    tool_tokens = sum(item.count.value for item in tool_counts)
    input_tokens = sum(item.count.value for item in block_counts) + tool_tokens
    required_tokens = sum(item.count.value for item in block_counts if item.required) + tool_tokens
    if required_tokens > token_budget:
        message = f"Required Core content count {required_tokens} exceeds budget {token_budget}."
        raise RelicError(
            "CONTEXT_OVERFLOW",
            message,
            details=(
                Diagnostic(code="CONTEXT_OVERFLOW", message=message, location=("token_budget",)),
            ),
        )
    retained_tokens = input_tokens
    omissions: list[BudgetOmission] = []
    for block, counted in reversed(tuple(zip(blocks, block_counts, strict=True))):
        if retained_tokens <= token_budget:
            break
        if block.kind == "memory" and not block.required:
            omissions.append(
                BudgetOmission(
                    block_id=block.block_id,
                    source=ModuleSource(
                        key=block.source_key,
                        content_hash=block.source_hash,
                        relative_path=block.source_relative_path,
                    ),
                    original_order=block.order,
                    tokens=counted.count.value,
                )
            )
            retained_tokens -= counted.count.value
    omitted_ids = {item.block_id for item in omissions}
    counts = [item.count for item in block_counts] + [item.count for item in tool_counts]
    report = BudgetReport(
        token_budget=token_budget,
        counter_id=counter_id,
        estimated=not counts or not all(item.exact for item in counts),
        input_tokens=input_tokens,
        retained_tokens=retained_tokens,
        required_tokens=required_tokens,
        tool_tokens=tool_tokens,
        block_counts=block_counts,
        tool_counts=tool_counts,
        omissions=tuple(omissions),
    )
    return BudgetDecision(
        blocks=tuple(block for block in blocks if block.block_id not in omitted_ids),
        report=report,
        diagnostics=tuple(
            Diagnostic(
                severity="warning",
                code="CONTEXT_OVERFLOW",
                message="Optional Memory omitted to satisfy the Core content budget.",
                source=item.source.relative_path,
                location=("budget", item.block_id),
            )
            for item in omissions
        ),
    )
