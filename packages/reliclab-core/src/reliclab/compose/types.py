"""Composition requests, provenance, and immutable serialized IR results."""

import json
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

from reliclab.resolve import CompositionLock, LockedModule
from reliclab.resolve.types import Digest, canonical_json, digest
from reliclab.schema import Diagnostic, ModuleId, ModuleKey, ToolRequirement
from reliclab.schema.models import StrictModel
from reliclab.schema.types import RelativePath, Scalar, sequence_input

VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$(?![\s\S])")]
Trust = Literal["instruction", "reference"]


class ComposeRequest(StrictModel):
    variables: dict[VariableName, Scalar] = Field(default_factory=dict)
    selected_memory_ids: Annotated[tuple[ModuleId, ...], BeforeValidator(sequence_input)] = ()
    trusted_sources: Annotated[tuple[LockedModule, ...], BeforeValidator(sequence_input)] = ()
    token_budget: Annotated[int, Field(ge=1, le=1000000)] | None = None
    counter_id: Literal["unmeasured"] = "unmeasured"
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


class BudgetReport(StrictModel):
    status: Literal["not_evaluated"] = "not_evaluated"
    token_budget: Annotated[int, Field(ge=1, le=1000000)]
    counter_id: Literal["unmeasured"] = "unmeasured"


class CompositionManifest(StrictModel):
    composer_version: Literal["1.0"] = "1.0"
    schema_version: Literal["1.0"] = "1.0"
    renderer_version: Literal["unrendered"] = "unrendered"
    counter_id: Literal["unmeasured"] = "unmeasured"
    composition_lock: CompositionLock
    sources: tuple[ModuleSource, ...]
    variables: dict[VariableName, Scalar]
    selected_memory_ids: tuple[ModuleId, ...]
    trusted_sources: tuple[LockedModule, ...]
    limits: ComposeLimits


class ContextData(StrictModel):
    ir_version: Literal["1.0"] = "1.0"
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
