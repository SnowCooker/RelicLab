"""Public validation with stable, value-free diagnostics."""

from typing import Literal

from pydantic import Field, TypeAdapter, ValidationError

from .models import ModuleDocument, StrictModel

ErrorCode = Literal[
    "PARSE_ERROR",
    "SCHEMA_INVALID",
    "SOURCE_CHANGED",
    "NOT_FOUND",
    "VERSION_CONFLICT",
    "DEPENDENCY_CYCLE",
    "PATH_DENIED",
    "CONTEXT_OVERFLOW",
    "IO_ERROR",
]


class Diagnostic(StrictModel):
    severity: Literal["error", "warning", "info"] = "error"
    code: ErrorCode
    message: str
    source: str | None = None
    location: tuple[str | int, ...] = ()
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    exact: bool = False


class RelicError(Exception):
    """A domain failure without raw asset values or fabricated line numbers."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        location: tuple[str | int, ...] = (),
        details: tuple[Diagnostic, ...] = (),
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.location = location
        self.details = details
        self.retryable = retryable


DOCUMENT_ADAPTER: TypeAdapter[ModuleDocument] = TypeAdapter(ModuleDocument)


def validate_module(
    data: object, *, source: str | None = None, max_body_bytes: int = 1024 * 1024
) -> ModuleDocument:
    """Validate a decoded document; raw frontmatter decoding belongs to the codec."""
    if type(max_body_bytes) is not int or max_body_bytes < 1:
        raise ValueError("max_body_bytes must be a positive integer")
    try:
        return DOCUMENT_ADAPTER.validate_python(data, context={"max_body_bytes": max_body_bytes})
    except ValidationError as error:
        diagnostics = []
        for item in error.errors(include_url=False, include_context=False, include_input=False):
            location = item["loc"]
            if location and location[0] in ("persona", "skill", "memory", "composition"):
                location = location[1:]
            diagnostics.append(
                Diagnostic(
                    code="SCHEMA_INVALID",
                    source=source,
                    location=location,
                    message=f"Invalid field ({item['type']}); follow the constraint in SPEC.md.",
                )
            )
        raise RelicError(
            "SCHEMA_INVALID",
            "Asset validation failed; inspect field diagnostics.",
            location=diagnostics[0].location,
            details=tuple(diagnostics),
        ) from None
