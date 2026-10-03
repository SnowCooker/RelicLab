"""Single-pass scalar substitution, not a general-purpose template engine."""

import re
from collections.abc import Mapping

from reliclab.resolve.types import canonical_json
from reliclab.schema import Diagnostic, RelicError
from reliclab.schema.types import Scalar

TOKEN = re.compile(r"{{([^{}]*)}}|{{|}}|{%|%}|{#|#}")
IDENTIFIER = re.compile(r"[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*")


class TextBuilder:
    """Bound accumulated UTF-8 text before joining separately expanded fields."""

    def __init__(self, max_bytes: int, separator: str = "\n\n") -> None:
        self.parts: list[str] = []
        self.size = 0
        self.max_bytes = max_bytes
        self.separator = separator

    def append(self, value: str) -> None:
        self.size += len(value.encode("utf-8"))
        if self.parts:
            self.size += len(self.separator.encode("utf-8"))
        if self.size > self.max_bytes:
            raise RelicError("CONTEXT_OVERFLOW", "Composed block exceeds its byte limit.")
        self.parts.append(value)

    def text(self) -> str:
        return self.separator.join(self.parts)


def substitute(
    text: str,
    variables: Mapping[str, Scalar],
    *,
    source: str,
    location: tuple[str | int, ...],
    max_bytes: int,
) -> str:
    parts: list[str] = []
    size = 0
    previous = 0

    def append(value: str) -> None:
        nonlocal size
        try:
            size += len(value.encode("utf-8"))
        except UnicodeError:
            raise RelicError("SCHEMA_INVALID", "Composition text must be valid UTF-8.") from None
        if size > max_bytes:
            raise RelicError("CONTEXT_OVERFLOW", "Template output exceeds its byte limit.")
        parts.append(value)

    for token in TOKEN.finditer(text):
        append(text[previous : token.start()])
        identifier = IDENTIFIER.fullmatch(token.group(1) or "")
        if (
            identifier is None
            or (token.start() > 0 and text[token.start() - 1] == "{")
            or (token.end() < len(text) and text[token.end()] == "}")
        ):
            message = "Only scalar identifier substitutions are supported."
            raise RelicError(
                "SCHEMA_INVALID",
                message,
                details=(
                    Diagnostic(
                        code="SCHEMA_INVALID", message=message, source=source, location=location
                    ),
                ),
            )
        name = identifier.group(1)
        if name not in variables:
            message = "A required template variable is missing."
            raise RelicError(
                "SCHEMA_INVALID",
                message,
                details=(
                    Diagnostic(
                        code="SCHEMA_INVALID", message=message, source=source, location=location
                    ),
                ),
            )
        value = variables[name]
        append(value if isinstance(value, str) else canonical_json(value))
        previous = token.end()
    append(text[previous:])
    return "".join(parts)
