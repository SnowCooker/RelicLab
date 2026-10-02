"""Strict portable primitives shared by asset models."""

import re
from typing import Annotated, Any

from pydantic import AfterValidator, Field, ValidationInfo
from semver import Version

END = r"$(?![\s\S])"
ID_PATTERN = r"^[a-z][a-z0-9-]{0,63}" + END
NUMBER = r"(?:0|[1-9][0-9]*)"
PRE = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
VERSION_PATTERN = (
    rf"{NUMBER}\.{NUMBER}\.{NUMBER}"
    rf"(?:-{PRE}(?:\.{PRE})*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
SELECTOR_PATTERN = rf"(?:{NUMBER}(?:\.{NUMBER})?|\^?{VERSION_PATTERN})"
REF_PATTERN = rf"^[a-z][a-z0-9-]{{0,63}}(?:@{SELECTOR_PATTERN})?" + END
RESERVED = {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in "123456789\u00b9\u00b2\u00b3"
}


def portable_id(value: str) -> str:
    if value in RESERVED:
        raise ValueError("Use a non-reserved portable identifier")
    return value


def semantic_version(value: str) -> str:
    Version.parse(value)
    return value


def module_ref(value: str) -> str:
    identifier, _, selector = value.partition("@")
    portable_id(identifier)
    if selector.count(".") >= 2:
        semantic_version(selector.removeprefix("^"))
    return value


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Provide non-whitespace text")
    return value


def body_size(value: str, info: ValidationInfo) -> str:
    limit = info.context["max_body_bytes"] if info.context else 1024 * 1024
    if len(value.encode("utf-8")) > limit:
        raise ValueError("Body exceeds the host's UTF-8 byte limit")
    return value


def sequence_input(value: Any) -> Any:
    # JSON arrays become immutable sequences without coercing their elements.
    return tuple(value) if isinstance(value, list) else value


def relative_path(value: str) -> str:
    parts = value.split("/")
    if (
        not value
        or any(part in ("", ".", "..") for part in parts)
        or any(char in value for char in '\\:<>|"\x00')
        or any(ord(char) < 32 for char in value)
        or any(part.endswith((" ", ".")) for part in parts)
        or any(part.split(".")[0].rstrip(" ").lower() in RESERVED for part in parts)
    ):
        raise ValueError("Use a portable relative path with forward slashes")
    return value


ModuleId = Annotated[
    str, Field(strict=True, pattern=re.compile(ID_PATTERN)), AfterValidator(portable_id)
]
AssetVersion = Annotated[
    str,
    Field(strict=True, pattern=re.compile(rf"^{VERSION_PATTERN}" + END)),
    AfterValidator(semantic_version),
]
ModuleRef = Annotated[
    str, Field(strict=True, pattern=re.compile(REF_PATTERN)), AfterValidator(module_ref)
]
NonBlank = Annotated[str, Field(pattern=r"\S"), AfterValidator(nonblank)]
Body = Annotated[str, AfterValidator(body_size)]
RelativePath = Annotated[str, AfterValidator(relative_path)]
Scalar = str | bool | int | float | None


def has_glob(value: str) -> bool:
    return re.search(r"[*?\[\]]", value) is not None
