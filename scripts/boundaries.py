"""Static architecture checks for ordinary and literal dynamic imports.

This is a dependency regression guard, not a security sandbox.
"""

import ast
import sys
from pathlib import Path

from scripts.config import Package


def imports_in(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    imports: list[tuple[int, str]] = []
    importlib_names = {"importlib"}
    dynamic_functions = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if not node.level and node.module:
                imports.append((node.lineno, node.module))
            if node.module == "importlib":
                dynamic_functions.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "import_module"
                )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        dynamic = (isinstance(function, ast.Name) and function.id in dynamic_functions) or (
            isinstance(function, ast.Attribute)
            and function.attr == "import_module"
            and isinstance(function.value, ast.Name)
            and function.value.id in importlib_names
        )
        if dynamic:
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                name = node.args[0].value
                if not name.startswith("."):
                    imports.append((node.lineno, name))
            else:
                imports.append((node.lineno, "<unresolved-dynamic-import>"))
    return imports


def check_package(root: Path, package: Package) -> list[str]:
    allowed = {
        *sys.stdlib_module_names,
        "__future__",
        package["module"],
        *package["allowed_internal"],
        *package["allowed_external"],
    }
    violations: list[str] = []
    source_root = root / package["path"] / "src" / package["module"]
    if not source_root.is_dir():
        return [f"Missing package source: {source_root}"]
    for path in sorted(source_root.rglob("*.py")):
        for line, name in imports_in(path.read_text(encoding="utf-8")):
            if name.split(".")[0] not in allowed:
                violations.append(f"{path.relative_to(root)}:{line}: forbidden import {name}")
    return violations
