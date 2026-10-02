"""Coverage gates must not average a failing package into a passing one."""

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import coverage_gate
from scripts.config import CoverageGroup

GROUPS: list[CoverageGroup] = [
    {"name": "core", "prefixes": ["core/"], "line_min": 90, "branch_min": 85},
    {"name": "runtime", "prefixes": ["runtime/"], "line_min": 90, "branch_min": 85},
]


def report(lines: int = 90, branches: int = 85) -> dict[str, Any]:
    return {
        "files": {
            "core/main.py": {
                "summary": {
                    "covered_lines": lines,
                    "num_statements": 100,
                    "covered_branches": branches,
                    "num_branches": 100,
                }
            },
            "runtime\\main.py": {
                "summary": {
                    "covered_lines": 100,
                    "num_statements": 100,
                    "covered_branches": 0,
                    "num_branches": 0,
                }
            },
        }
    }


def test_exact_threshold_and_windows_path() -> None:
    assert coverage_gate.evaluate(report(), GROUPS) == []


@pytest.mark.parametrize("lines,branches", [(89, 100), (100, 84)])
def test_failing_package_cannot_be_hidden(lines: int, branches: int) -> None:
    failures = coverage_gate.evaluate(report(lines, branches), GROUPS)
    assert len(failures) == 1
    assert failures[0].startswith("core")


def test_missing_measurements_fail() -> None:
    assert len(coverage_gate.evaluate({"files": {}}, GROUPS)) == 2


def test_main_success_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "coverage.json"
    monkeypatch.setattr(coverage_gate, "load_config", lambda root: {"coverage_groups": GROUPS})
    path.write_text(json.dumps(report()), encoding="utf-8")
    assert coverage_gate.main([str(path)]) == 0
    assert coverage_gate.main([str(path), "--group", "core"]) == 0
    assert coverage_gate.main([str(path), "--group", "unknown"]) == 1
    core_only = report()
    del core_only["files"]["runtime\\main.py"]
    path.write_text(json.dumps(core_only), encoding="utf-8")
    assert coverage_gate.main([str(path), "--group", "core"]) == 0
    assert coverage_gate.main([str(path)]) == 1
    path.write_text(json.dumps(report(80)), encoding="utf-8")
    assert coverage_gate.main([str(path)]) == 1
    path.write_text("not json", encoding="utf-8")
    assert coverage_gate.main([str(path)]) == 1
