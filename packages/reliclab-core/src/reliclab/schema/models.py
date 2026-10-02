"""Version 1.0 asset DTOs; no filesystem or agent execution behavior."""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from .tools import validate_tool_schema
from .types import (
    END,
    AssetVersion,
    Body,
    ModuleId,
    ModuleRef,
    NonBlank,
    RelativePath,
    Scalar,
    has_glob,
    sequence_input,
)

Kind = Literal["persona", "skill", "memory", "composition"]
Strings = Annotated[tuple[str, ...], BeforeValidator(sequence_input)]
References = Annotated[tuple[ModuleRef, ...], BeforeValidator(sequence_input)]
Tags = Annotated[
    tuple[Annotated[str, Field(max_length=64)], ...],
    BeforeValidator(sequence_input),
    Field(max_length=32),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        revalidate_instances="always",
        regex_engine="python-re",
    )


class ModuleKey(StrictModel):
    kind: Kind
    id: ModuleId
    version: AssetVersion


class Asset(StrictModel):
    schema_version: Literal["1.0"]
    id: ModuleId
    kind: Kind
    version: AssetVersion
    name: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    description: Annotated[str, Field(max_length=2000)] = ""
    tags: Tags = ()
    author: Annotated[str, Field(max_length=120)] | None = None
    extensions: dict[Annotated[str, Field(pattern=r"^x-")], JsonValue] = Field(default_factory=dict)
    body: Body = ""

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value))

    @property
    def key(self) -> ModuleKey:
        return ModuleKey(kind=self.kind, id=self.id, version=self.version)


class Persona(Asset):
    kind: Literal["persona"]
    identity: NonBlank
    voice: str = ""
    values: Strings = ()
    constraints: Strings = ()
    extends: ModuleRef | None = None


class ToolRequirement(StrictModel):
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}" + END)]
    input_schema: dict[str, JsonValue]
    description: str

    @field_validator("input_schema")
    @classmethod
    def supported_schema(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return validate_tool_schema(value)


class SkillExample(StrictModel):
    input: str
    output: str


class Skill(Asset):
    kind: Literal["skill"]
    trigger: str = ""
    tools: Annotated[tuple[ToolRequirement, ...], BeforeValidator(sequence_input)] = ()
    examples: Annotated[tuple[SkillExample, ...], BeforeValidator(sequence_input)] = ()
    body: Annotated[Body, Field(pattern=r"\S")]


class Memory(Asset):
    kind: Literal["memory"]
    source: Literal["inline", "file", "glob"]
    root: ModuleId | None = None
    path: RelativePath | None = None
    scope: Literal["always", "on-demand"] = "on-demand"
    depth: Annotated[int, Field(ge=0, le=1)] = 0

    @model_validator(mode="after")
    def source_contract(self) -> Self:
        if self.source == "inline":
            if self.root is not None or self.path is not None or not self.body.strip():
                raise ValueError("Inline memory needs a body and no root or path")
        elif self.root is None or self.path is None or self.body != "":
            raise ValueError("File and glob memory need root and path, and an empty body")
        elif self.source == "file" and has_glob(self.path):
            raise ValueError("Use source glob for wildcard paths")
        return self


class ModuleSelection(StrictModel):
    persona: ModuleRef | None = None
    skills: References = ()
    memory: References = ()

    @field_validator("skills", "memory")
    @classmethod
    def unique_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        ids = [reference.partition("@")[0] for reference in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Select each module ID once per slot")
        return value

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if self.persona is None and not self.skills and not self.memory:
            raise ValueError("Select at least one persona, skill, or memory")
        return self


class RenderOptions(StrictModel):
    target: Literal["plain", "openai-chat", "anthropic-messages"]
    token_budget: Annotated[int, Field(ge=1, le=1_000_000)] = 8000


class Composition(Asset):
    kind: Literal["composition"]
    modules: ModuleSelection
    variables: dict[str, Scalar] = Field(default_factory=dict)
    render: RenderOptions


ModuleDocument = Annotated[Persona | Skill | Memory | Composition, Field(discriminator="kind")]
