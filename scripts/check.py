"""Run installed quality tools without installing or updating dependencies."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Runner = Callable[[list[str], Path, dict[str, str]], int]


def run_command(command: list[str], root: Path, env: dict[str, str]) -> int:
    print(f"Running: {subprocess.list2cmdline(command)}", flush=True)
    return subprocess.run(command, cwd=root, env=env, check=False).returncode


def main(argv: Sequence[str] | None = None, *, runner: Runner = run_command) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stage")
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--packaging", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    with (ROOT / "tests/quality.toml").open("rb") as source:
        config = tomllib.load(source)
    if config.get("schema_version") != 1:
        parser.error("Unsupported quality configuration version")
    stages = config["stages"]
    if args.stage is not None and args.stage not in stages:
        parser.error(f"Stage {args.stage!r} is not implemented; available: {', '.join(stages)}")

    tools = (
        ["build", "hatchling"]
        if args.packaging
        else [
            "ruff",
            "mypy",
            "pytest",
            "pytest_cov",
            "pytest_socket",
        ]
    )
    missing = [name for name in tools if importlib.util.find_spec(name) is None]
    if missing:
        print(
            f"Missing tools: {', '.join(missing)}. Run: "
            "uv sync --all-packages --all-extras --dev --locked",
            file=sys.stderr,
        )
        return 2
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    if args.offline or args.packaging:
        env.update(UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never", PIP_NO_INDEX="1")
    python = sys.executable
    commands: list[list[str]]
    if args.packaging:
        commands = [[python, "-m", "scripts.packaging"]]
    else:
        selected = [stages[args.stage]] if args.stage else list(stages.values())
        paths = list(dict.fromkeys(path for stage in selected for path in stage["paths"]))
        tests = list(dict.fromkeys(path for stage in selected for path in stage["tests"]))
        coverage = list(dict.fromkeys(name for stage in selected for name in stage["coverage"]))
        if not tests:
            parser.error("Selected stages contain no tests")
        commands = [
            [python, "-m", "ruff", "check", *paths],
            [python, "-m", "ruff", "format", "--check", *paths],
            [python, "-m", "mypy", *paths],
            [
                python,
                "-m",
                "pytest",
                *tests,
                "-m",
                "not live and not packaging",
                *[f"--cov={name}" for name in coverage],
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-report=json:.artifacts/coverage.json",
                *(["--disable-socket"] if args.offline else []),
            ],
            [
                python,
                "-m",
                "scripts.coverage_gate",
                ".artifacts/coverage.json",
                *[
                    item
                    for group in dict.fromkeys(
                        name for stage in selected for name in stage.get("groups", [])
                    )
                    for item in ("--group", group)
                ],
            ],
        ]
    artifact_dir = ROOT / ".artifacts"
    artifact_dir.mkdir(exist_ok=True)
    results: list[dict[str, object]] = []
    exit_code = 0
    for command in commands:
        try:
            exit_code = runner(command, ROOT, env)
        except OSError as error:
            print(f"Could not execute quality tool: {error}", file=sys.stderr)
            exit_code = 1
        results.append({"command": command, "exit_code": exit_code})
        if exit_code:
            break
    report_name = f"check-{args.stage or ('packaging' if args.packaging else 'all')}.json"
    (artifact_dir / report_name).write_text(
        json.dumps({"stage": args.stage, "offline": args.offline, "checks": results}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return exit_code if exit_code >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
