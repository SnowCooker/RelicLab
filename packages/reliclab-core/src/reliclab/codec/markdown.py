"""Markdown envelope handling, validation diagnostics, and canonical JSON/YAML output."""

import json
from types import MappingProxyType
from typing import Any

from reliclab.schema import Diagnostic, ModuleDocument, RelicError, validate_module

from .types import CodecLimits, ParsedModule, SourcePosition
from .yaml import decode, fail

DEFAULT_LIMITS = CodecLimits()


def envelope(
    text: str | bytes, source: str, limits: CodecLimits
) -> tuple[str, str, SourcePosition]:
    if len(text) > limits.max_frontmatter_bytes + limits.max_body_bytes + 13:
        fail("Asset exceeds the combined byte limit", source, SourcePosition(1, 1), exact=False)
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError:
            fail("Asset must contain valid UTF-8", source, SourcePosition(1, 1), exact=False)
    text = text.removeprefix("\ufeff")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        fail("Asset must contain valid UTF-8", source, SourcePosition(1, 1), exact=False)
    if not text.startswith(("---\n", "---\r\n")):
        fail("Asset must start with a frontmatter delimiter", source, SourcePosition(1, 1))
    start = text.index("\n") + 1
    cursor, line, size = start, 2, 0
    while cursor < len(text):
        end = text.find("\n", cursor)
        next_cursor = len(text) if end < 0 else end + 1
        raw = text[cursor:next_cursor]
        if raw in ("---", "---\n", "---\r\n"):
            body = text[next_cursor:]
            point = SourcePosition(line, 4) if end < 0 else SourcePosition(line + 1, 1)
            if len(body.encode("utf-8")) > limits.max_body_bytes:
                fail("Body exceeds the byte limit", source, point, ("body",))
            return text[start:cursor], body, point
        size += len(raw.encode("utf-8"))
        if size > limits.max_frontmatter_bytes:
            fail("Frontmatter exceeds the byte limit", source, SourcePosition(line, 1))
        content = raw[:-2] if raw.endswith("\r\n") else raw.removesuffix("\n")
        if any(char in content for char in "\r\x85\u2028\u2029"):
            fail("Frontmatter line endings must be LF or CRLF", source, SourcePosition(line, 1))
        cursor = next_cursor
        line += 1
    fail("Missing closing frontmatter delimiter", source, SourcePosition(1, 1))


def parse_with_source(
    text: str | bytes, source: str = "<memory>", *, limits: CodecLimits = DEFAULT_LIMITS
) -> ParsedModule:
    """Decode UTF-8 Markdown without I/O; retain body text and source positions."""
    header, body, body_position = envelope(text, source, limits)
    data, positions = decode(header, source, limits)
    if "body" in data:
        fail(
            "Body must follow the closing delimiter, not be a metadata field",
            source,
            positions[("body",)],
            ("body",),
        )
    positions[("body",)] = body_position
    data["body"] = body
    try:
        document = validate_module(data, source=source, max_body_bytes=limits.max_body_bytes)
    except RelicError as error:
        details = []
        for item in error.details:
            point = positions.get(item.location, SourcePosition(2, 1))
            details.append(
                item.model_copy(
                    update={
                        "line": point.line,
                        "column": point.column,
                        "exact": item.location in positions,
                    }
                )
            )
        raise RelicError(
            error.code, error.message, location=error.location, details=tuple(details)
        ) from None
    return ParsedModule(document, MappingProxyType(positions))


def parse_module(
    text: str | bytes, source: str = "<memory>", *, limits: CodecLimits = DEFAULT_LIMITS
) -> ModuleDocument:
    """Parse a document; use parse_with_source when field coordinates are needed."""
    return parse_with_source(text, source, limits=limits).document


def ordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ordered(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [ordered(item) for item in value]
    return value


def serialize_module(document: ModuleDocument, *, limits: CodecLimits = DEFAULT_LIMITS) -> str:
    """Return canonical LF Markdown; comments and input formatting are not retained."""
    validated = validate_module(document, max_body_bytes=limits.max_body_bytes)
    try:
        metadata = validated.model_dump(mode="json", exclude={"body"})
        header = json.dumps(
            {key: ordered(value) for key, value in metadata.items()},
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
        )
    except ValueError:
        message = "Asset cannot be encoded as canonical JSON"
        raise RelicError(
            "SCHEMA_INVALID",
            message,
            details=(Diagnostic(code="SCHEMA_INVALID", message=message),),
        ) from None
    body = validated.body.replace("\r\n", "\n").replace("\r", "\n")
    if body and not body.endswith("\n"):
        body += "\n"
    output = f"---\n{header}\n---\n{body}"
    # Enforce the same byte, depth, and node limits on emitted documents.
    parse_module(output, limits=limits)
    return output
