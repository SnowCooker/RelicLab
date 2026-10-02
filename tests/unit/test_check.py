"""Verify fail-closed quality orchestration and exit-code propagation."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from scripts import check


def configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/quality.toml").write_text(
        'schema_version = 1\n[stages.S00]\npaths = ["scripts"]\n'
        'tests = ["tests/unit"]\ncoverage = ["scripts.check"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "ROOT", tmp_path)


@pytest.mark.parametrize("args", [[], ["--stage", "S99"], ["--all", "--packaging"]])
def test_invalid_selection(args: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        check.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize("mode", [["--stage", "S00"], ["--all"]])
def test_quality_plan_and_offline_environment(
    mode: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def runner(command: list[str], root: Path, env: dict[str, str]) -> int:
        assert root == tmp_path
        assert env["UV_OFFLINE"] == "1"
        assert env["PIP_NO_INDEX"] == "1"
        calls.append(command)
        return 0

    assert check.main([*mode, "--offline"], runner=runner) == 0
    assert len(calls) == 5
    assert "--disable-socket" in calls[3]
    assert "--cov=scripts.check" in calls[3]
    assert all("sync" not in command and "install" not in command for command in calls)
    report_name = "check-S00.json" if "--stage" in mode else "check-all.json"
    report = json.loads((tmp_path / ".artifacts" / report_name).read_text())
    assert len(report["checks"]) == 5


def test_packaging_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configure(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def runner(command: list[str], root: Path, env: dict[str, str]) -> int:
        calls.append(command)
        assert env["UV_OFFLINE"] == "1"
        return 0

    assert check.main(["--packaging"], runner=runner) == 0
    assert calls == [[sys.executable, "-m", "scripts.packaging"]]


@pytest.mark.parametrize("code", [1, 7, -9])
def test_failure_stops_later_checks(
    code: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def runner(command: list[str], root: Path, env: dict[str, str]) -> int:
        calls.append(command)
        return code

    assert check.main(["--all"], runner=runner) == (code if code >= 0 else 1)
    assert len(calls) == 1


def test_subprocess_exit_code_is_not_swallowed(tmp_path: Path) -> None:
    assert check.run_command([sys.executable, "-c", "raise SystemExit(9)"], tmp_path, {}) == 9


def test_missing_tool_fails_without_installing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert check.main(["--all"]) == 2
    assert "uv sync" in capsys.readouterr().err


def test_os_error_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configure(monkeypatch, tmp_path)

    def runner(command: list[str], root: Path, env: dict[str, str]) -> int:
        raise OSError("Execution unavailable")

    assert check.main(["--all"], runner=runner) == 1


def test_empty_test_selection_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configure(monkeypatch, tmp_path)
    path = tmp_path / "tests/quality.toml"
    path.write_text(path.read_text().replace('tests = ["tests/unit"]', "tests = []"))
    with pytest.raises(SystemExit) as error:
        check.main(["--all"])
    assert error.value.code == 2


def test_unknown_config_version_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path)
    path = tmp_path / "tests/quality.toml"
    path.write_text(path.read_text().replace("schema_version = 1", "schema_version = 99"))
    with pytest.raises(SystemExit) as error:
        check.main(["--all"])
    assert error.value.code == 2
