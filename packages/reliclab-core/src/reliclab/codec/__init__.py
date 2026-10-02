"""Pure, bounded Markdown asset decoding and canonical encoding."""

from .markdown import parse_module, parse_with_source, serialize_module
from .types import CodecLimits, ParsedModule, SourcePosition

__all__ = [
    "CodecLimits",
    "ParsedModule",
    "SourcePosition",
    "parse_module",
    "parse_with_source",
    "serialize_module",
]
