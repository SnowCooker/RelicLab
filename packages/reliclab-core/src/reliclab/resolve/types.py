"""Portable lock records and immutable resolution results."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from reliclab.schema import Composition, Diagnostic, ModuleKey, RelicError, validate_module
from reliclab.schema.models import StrictModel
from reliclab.schema.types import sequence_input
from reliclab.schema.validation import ErrorCode
from reliclab.vault import ModuleSnapshot

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$(?![\s\S])")]
MAX_LOCK_BYTES = 4 * 1024 * 1024


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (ValueError, TypeError):
        raise RelicError(
            "SCHEMA_INVALID", "Data cannot be represented as canonical JSON."
        ) from None


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


class LockedModule(StrictModel):
    key: ModuleKey
    content_hash: Digest


class CompositionLock(StrictModel):
    lock_version: Literal["1.0"] = "1.0"
    resolver_version: Literal["1.0"] = "1.0"
    composition_hash: Digest
    modules: Annotated[
        tuple[LockedModule, ...], BeforeValidator(sequence_input), Field(max_length=10000)
    ]

    @model_validator(mode="after")
    def unique_identities(self) -> Self:
        identities = [(item.key.kind, item.key.id) for item in self.modules]
        if len(identities) != len(set(identities)):
            raise ValueError("Lock entries must have unique typed module IDs")
        if any(item.key.kind == "composition" for item in self.modules):
            raise ValueError("Composition is identified by composition_hash, not a module entry")
        return self

    def to_json(self) -> str:
        validated = type(self).model_validate(self)
        text = canonical_json(validated.model_dump(mode="json"))
        if len(text.encode("utf-8")) > MAX_LOCK_BYTES:
            raise RelicError("SCHEMA_INVALID", "Lock exceeds its byte limit.")
        return text

    @property
    def digest(self) -> str:
        return digest(self.to_json())

    @classmethod
    def from_json(cls, text: str | bytes) -> Self:
        try:
            raw = text.encode("utf-8") if isinstance(text, str) else text
            if len(raw) > MAX_LOCK_BYTES:
                raise ValueError("Lock exceeds its byte limit")
            return cls.model_validate(
                json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
            )
        except (ValueError, RecursionError):
            raise RelicError("SCHEMA_INVALID", "Invalid or unsupported composition lock.") from None


@dataclass(frozen=True)
class PersonaSection:
    key: ModuleKey
    text: str


@dataclass(frozen=True)
class EffectivePersona:
    key: ModuleKey
    identity: str
    voice: str
    values: tuple[str, ...]
    constraints: tuple[str, ...]
    sections: tuple[PersonaSection, ...]

    @property
    def body(self) -> str:
        return "\n\n".join(
            f"## Persona {section.key.id}@{section.key.version}\n\n{section.text}"
            for section in self.sections
        )


@dataclass(frozen=True)
class ResolvedGraph:
    composition_json: str = field(repr=False)
    persona_chain: tuple[ModuleSnapshot, ...]
    skills: tuple[ModuleSnapshot, ...]
    memory: tuple[ModuleSnapshot, ...]
    persona: EffectivePersona | None
    lock: CompositionLock
    max_body_bytes: int = field(repr=False)

    @property
    def composition(self) -> Composition:
        document = validate_module(
            json.loads(self.composition_json), max_body_bytes=self.max_body_bytes
        )
        assert isinstance(document, Composition)
        return document

    @property
    def modules(self) -> tuple[ModuleSnapshot, ...]:
        return self.persona_chain + self.skills + self.memory


class ResolutionError(RelicError):
    """A resolution failure with validated references, never raw asset content."""

    def __init__(self, code: ErrorCode, message: str, chain: tuple[str, ...]) -> None:
        self.chain = chain
        super().__init__(
            code,
            message,
            details=tuple(
                Diagnostic(code=code, message=message, source=reference) for reference in chain
            ),
        )
