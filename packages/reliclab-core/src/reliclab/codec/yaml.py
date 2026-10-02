"""Decode a restricted YAML tree without invoking any YAML constructors."""

import json
import math
import re
from typing import Any, NoReturn

import yaml
from yaml.error import Mark
from yaml.events import (
    AliasEvent,
    CollectionEndEvent,
    CollectionStartEvent,
    DocumentEndEvent,
    DocumentStartEvent,
    NodeEvent,
    ScalarEvent,
)
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from reliclab.schema import Diagnostic, RelicError

from .types import CodecLimits, FieldPath, SourcePosition

NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def fail(
    message: str, source: str, position: SourcePosition, path: FieldPath = (), *, exact: bool = True
) -> NoReturn:
    raise RelicError(
        "PARSE_ERROR",
        message,
        location=path,
        details=(
            Diagnostic(
                code="PARSE_ERROR",
                message=message,
                source=source,
                location=path,
                line=position.line,
                column=position.column,
                exact=exact,
            ),
        ),
    ) from None


def position(mark: Mark) -> SourcePosition:
    # The YAML stream starts immediately after the opening Markdown delimiter.
    return SourcePosition(mark.line + 2, mark.column + 1)


def preflight(text: str, source: str, limits: CodecLimits) -> None:
    depth = nodes = documents = 0
    for event in yaml.parse(text, Loader=yaml.BaseLoader):
        point = position(event.start_mark)
        if isinstance(event, DocumentStartEvent):
            documents += 1
            if documents > 1 or event.explicit or event.version or event.tags:
                fail("YAML document markers and directives are not allowed", source, point)
        if isinstance(event, DocumentEndEvent) and event.explicit:
            fail("YAML document end markers are not allowed", source, point)
        if isinstance(event, NodeEvent):
            nodes += 1
            if nodes > limits.max_nodes:
                fail("Frontmatter exceeds the node limit", source, point)
            if event.anchor is not None or isinstance(event, AliasEvent):
                fail("YAML anchors and aliases are not allowed", source, point)
        if isinstance(event, (ScalarEvent, CollectionStartEvent)):
            if event.tag is not None:
                fail("Explicit YAML tags are not allowed", source, point)
            if depth + 1 > limits.max_depth:
                fail("Frontmatter exceeds the nesting limit", source, point)
        if isinstance(event, CollectionStartEvent):
            depth += 1
        elif isinstance(event, CollectionEndEvent):
            depth -= 1


def decode(
    text: str, source: str, limits: CodecLimits
) -> tuple[dict[str, Any], dict[FieldPath, SourcePosition]]:
    positions: dict[FieldPath, SourcePosition] = {}

    def visit(node: Node, path: FieldPath) -> Any:
        positions[path] = position(node.start_mark)
        if isinstance(node, MappingNode):
            result: dict[str, Any] = {}
            for key, value in node.value:
                if not isinstance(key, ScalarNode):
                    fail("Mapping keys must be strings", source, position(key.start_mark), path)
                name = scalar(key, source, path)
                if not isinstance(name, str):
                    fail("Mapping keys must be strings", source, position(key.start_mark), path)
                if name == "<<" or name in result:
                    fail(
                        "Merge keys and duplicate keys are not allowed",
                        source,
                        position(key.start_mark),
                        (*path, name),
                    )
                result[name] = visit(value, (*path, name))
            return result
        if isinstance(node, SequenceNode):
            return [visit(value, (*path, index)) for index, value in enumerate(node.value)]
        assert isinstance(node, ScalarNode)
        return scalar(node, source, path)

    try:
        preflight(text, source, limits)
        root = yaml.compose(text, Loader=yaml.BaseLoader)
        if not isinstance(root, MappingNode):
            fail("Frontmatter must be a mapping", source, SourcePosition(2, 1), exact=False)
        return visit(root, ()), positions
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        fail(
            "Malformed YAML frontmatter",
            source,
            position(mark) if mark is not None else SourcePosition(2, 1),
            exact=mark is not None,
        )


def scalar(node: ScalarNode, source: str, path: FieldPath) -> Any:
    value: Any = node.value
    try:
        if node.style is None:
            if node.value in ("null", "true", "false") or NUMBER.fullmatch(node.value):
                if len(node.value) > 1024:
                    raise ValueError("Numeric token exceeds the safety limit")
                value = json.loads(node.value)
            elif node.value == "":
                value = None
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite number")
        if isinstance(value, str):
            # JSON surrogate pairs are legal escapes; lone surrogates are not UTF-8 text.
            value = value.encode("utf-16-le", "surrogatepass").decode("utf-16-le")
        return value
    except ValueError:
        fail("Invalid UTF-8 scalar or numeric value", source, position(node.start_mark), path)
