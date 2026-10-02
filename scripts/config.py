"""Typed access to the version-controlled quality configuration."""

import tomllib
from pathlib import Path
from typing import NotRequired, TypedDict, cast


class Stage(TypedDict):
    paths: list[str]
    tests: list[str]
    coverage: list[str]
    groups: NotRequired[list[str]]


class CoverageGroup(TypedDict):
    name: str
    prefixes: list[str]
    line_min: int
    branch_min: int


class Package(TypedDict):
    path: str
    distribution: str
    module: str
    allowed_internal: list[str]
    allowed_external: list[str]


class Configuration(TypedDict):
    schema_version: int
    stages: dict[str, Stage]
    coverage_groups: list[CoverageGroup]
    packages: list[Package]


def load_config(root: Path) -> Configuration:
    with (root / "tests/quality.toml").open("rb") as source:
        data = tomllib.load(source)
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported quality configuration version")
    return cast(Configuration, data)
