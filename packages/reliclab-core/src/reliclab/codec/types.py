"""Host-controlled limits and read-only source coordinates."""

from collections.abc import Mapping
from dataclasses import dataclass

from reliclab.schema import ModuleDocument

FieldPath = tuple[str | int, ...]


@dataclass(frozen=True)
class CodecLimits:
    max_frontmatter_bytes: int = 64 * 1024
    max_body_bytes: int = 1024 * 1024
    max_depth: int = 32
    max_nodes: int = 10000

    def __post_init__(self) -> None:
        for value in (
            self.max_frontmatter_bytes,
            self.max_body_bytes,
            self.max_depth,
            self.max_nodes,
        ):
            if type(value) is not int or value < 1:
                raise ValueError("Codec limits must be positive integers")
        if self.max_depth > 64:
            raise ValueError("max_depth cannot exceed the hard safety ceiling of 64")


@dataclass(frozen=True)
class SourcePosition:
    line: int
    column: int


@dataclass(frozen=True)
class ParsedModule:
    document: ModuleDocument
    positions: Mapping[FieldPath, SourcePosition]
