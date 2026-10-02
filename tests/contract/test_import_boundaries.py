"""Verify source imports and distribution dependency direction."""

import re
import tomllib
from importlib import import_module
from pathlib import Path

import pytest

from scripts.boundaries import check_package, imports_in
from scripts.config import Package, load_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_config(ROOT)


@pytest.mark.parametrize("package", CONFIG["packages"], ids=lambda package: package["distribution"])
def test_real_package_boundary(package: Package) -> None:
    assert check_package(ROOT, package) == []


@pytest.mark.parametrize(
    "source",
    [
        "import reliclab_runtime\n",
        "from reliclab_cli.main import main\n",
        "import fastapi\n",
        "import openai\n",
        "import anthropic\n",
        "import importlib as loader\nloader.import_module('reliclab_server')\n",
        "from importlib import import_module as load\nload('reliclab_runtime')\n",
        "__import__('reliclab_runtime')\n",
        "__import__(variable_name)\n",
    ],
)
def test_injected_violation_is_rejected(source: str, tmp_path: Path) -> None:
    package = CONFIG["packages"][0]
    root = tmp_path / package["path"] / "src" / package["module"]
    root.mkdir(parents=True)
    (root / "bad.py").write_text(source, encoding="utf-8")
    assert len(check_package(tmp_path, package)) == 1
    (root / "bad.py").write_text("from pathlib import Path\n", encoding="utf-8")
    assert check_package(tmp_path, package) == []


def test_missing_package_is_not_success(tmp_path: Path) -> None:
    assert "Missing package" in check_package(tmp_path, CONFIG["packages"][0])[0]


def test_relative_imports_and_non_import_calls() -> None:
    assert imports_in("from . import helper\nprint('hello')\n") == []
    assert imports_in("import importlib\nimportlib.import_module('.helper', 'reliclab')") == [
        (1, "importlib")
    ]


def test_metadata_matches_dependency_direction() -> None:
    modules = {package["module"]: package["distribution"] for package in CONFIG["packages"]}
    for package in CONFIG["packages"]:
        with (ROOT / package["path"] / "pyproject.toml").open("rb") as source:
            project = tomllib.load(source)["project"]
        allowed = {modules[name] for name in package["allowed_internal"]} | set(
            package["allowed_external"]
        )
        dependencies = list(project["dependencies"])
        for extra in project.get("optional-dependencies", {}).values():
            dependencies.extend(extra)
        for dependency in dependencies:
            name = re.split(r"[\[<>=!;~ ]", dependency)[0]
            assert name in allowed


@pytest.mark.parametrize("module", [package["module"] for package in CONFIG["packages"]])
def test_all_packages_import_with_version(module: str) -> None:
    assert import_module(module).__version__ == "0.1.0a1"
