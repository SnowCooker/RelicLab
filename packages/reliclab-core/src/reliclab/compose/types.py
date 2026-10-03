"""Composition requests, provenance, and immutable serialized IR results."""

import json
from dataclasses import dataclass, field
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from reliclab.resolve import CompositionLock, LockedModule
from reliclab.resolve.types import Digest, canonical_json, digest
from reliclab.schema import Diagnostic, ModuleId, ModuleKey, ToolRequirement
from reliclab.schema.models import StrictModel
from reliclab.schema.types import RelativePath, Scalar, sequence_input

VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$(?![\s\S])")]
Trust = Literal["instruction", "reference"]
CounterId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$(?![\s\S])")]
TokenValue = Annotated[int, Field(ge=0)]


class ComposeRequest(StrictModel):
    variables: dict[VariableName, Scalar] = Field(default_factory=dict)
    selected_memory_ids: Annotated[tuple[ModuleId, ...], BeforeValidator(sequence_input)] = ()
    trusted_sources: Annotated[tuple[LockedModule, ...], BeforeValidator(sequence_input)] = ()
    token_budget: Annotated[int, Field(ge=1, le=1000000)] | None = None
    counter_id: CounterId = "utf8-bytes-v1"
    renderer_version: Literal["unrendered"] = "unrendered"


class ComposeLimits(StrictModel):
    max_block_bytes: Annotated[int, Field(ge=1)] = 1024 * 1024
    max_context_bytes: Annotated[int, Field(ge=1)] = 16 * 1024 * 1024
    max_variable_bytes: Annotated[int, Field(ge=1)] = 65536
    max_variables: Annotated[int, Field(ge=1)] = 256


class ModuleSource(StrictModel):
    key: ModuleKey
    content_hash: Digest
    relative_path: RelativePath


class ContextBlock(StrictModel):
    block_id: str
    kind: Literal["persona", "skill", "memory"]
    text: str
    source_key: ModuleKey
    source_hash: Digest
    source_relative_path: RelativePath
    required: bool
    trust: Trust
    order: Annotated[int, Field(ge=0)]


class ComposedTool(StrictModel):
    requirement: ToolRequirement
    sources: tuple[ModuleSource, ...]
    trust: Trust


class TokenCount(StrictModel):
    value: Annotated[int, Field(ge=0, le=9223372036854775807)]
    exact: bool
    counter_id: CounterId


class BlockTokenCount(StrictModel):
    block_id: str
    required: bool
    count: TokenCount


class ToolTokenCount(StrictModel):
    name: str
    count: TokenCount


class BudgetOmission(StrictModel):
    block_id: str
    source: ModuleSource
    original_order: Annotated[int, Field(ge=0)]
    tokens: TokenValue
    reason: Literal["token_budget"] = "token_budget"


class BudgetReport(StrictModel):
    status: Literal["within_budget"] = "within_budget"
    counting_scope: Literal["core-content-v1"] = "core-content-v1"
    token_budget: Annotated[int, Field(ge=1, le=1000000)]
    counter_id: CounterId
    estimated: bool
    input_tokens: TokenValue
    retained_tokens: TokenValue
    required_tokens: TokenValue
    tool_tokens: TokenValue
    block_counts: tuple[BlockTokenCount, ...]
    tool_counts: tuple[ToolTokenCount, ...]
    omissions: tuple[BudgetOmission, ...] = ()

    @model_validator(mode="after")
    def consistent_accounting(self) -> Self:
        blocks = {item.block_id: item for item in self.block_counts}
        omitted = {item.block_id for item in self.omissions}
        counts = [item.count for item in self.block_counts] + [
            item.count for item in self.tool_counts
        ]
        if (
            len(blocks) != len(self.block_counts)
            or len({item.name for item in self.tool_counts}) != len(self.tool_counts)
            or len(omitted) != len(self.omissions)
            or any(item.counter_id != self.counter_id for item in counts)
            or self.estimated != (not counts or not all(item.exact for item in counts))
        ):
            raise ValueError(
                "Budget measurements must have unique identities and consistent precision"
            )
        for item in self.omissions:
            block = blocks.get(item.block_id)
            if block is None or block.required or block.count.value != item.tokens:
                raise ValueError("Budget omissions must match optional measured blocks")
        tools = sum(item.count.value for item in self.tool_counts)
        before = sum(item.count.value for item in self.block_counts) + tools
        required = sum(item.count.value for item in self.block_counts if item.required) + tools
        retained = before - sum(item.tokens for item in self.omissions)
        if (
            self.tool_tokens != tools
            or self.input_tokens != before
            or self.required_tokens != required
            or self.retained_tokens != retained
            or retained > self.token_budget
        ):
            raise ValueError("Budget totals must reconcile and fit the requested budget")
        return self


class CompositionManifest(StrictModel):
    composer_version: Literal["1.1"] = "1.1"
    schema_version: Literal["1.0"] = "1.0"
    renderer_version: Literal["unrendered"] = "unrendered"
    counter_id: CounterId = "utf8-bytes-v1"
    composition_lock: CompositionLock
    sources: tuple[ModuleSource, ...]
    variables: dict[VariableName, Scalar]
    selected_memory_ids: tuple[ModuleId, ...]
    trusted_sources: tuple[LockedModule, ...]
    limits: ComposeLimits


class ContextData(StrictModel):
    ir_version: Literal["1.1"] = "1.1"
    blocks: tuple[ContextBlock, ...]
    tools: tuple[ComposedTool, ...]
    manifest: CompositionManifest
    diagnostics: tuple[Diagnostic, ...] = ()
    budget_report: BudgetReport


@dataclass(frozen=True)
class ComposedContext:
    """Canonical immutable bytes are authoritative; every DTO accessor is detached."""

    _payload_json: str = field(repr=False)

    @property
    def data(self) -> ContextData:
        return ContextData.model_validate_json(self._payload_json)

    @property
    def ir_version(self) -> str:
        return self.data.ir_version

    @property
    def blocks(self) -> tuple[ContextBlock, ...]:
        return self.data.blocks

    @property
    def tools(self) -> tuple[ComposedTool, ...]:
        return self.data.tools

    @property
    def manifest(self) -> CompositionManifest:
        return self.data.manifest

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self.data.diagnostics

    @property
    def budget_report(self) -> BudgetReport:
        return self.data.budget_report

    @property
    def digest(self) -> str:
        return digest(self._payload_json)

    def to_json(self) -> str:
        return canonical_json({**json.loads(self._payload_json), "digest": self.digest})
