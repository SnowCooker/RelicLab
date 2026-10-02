"""Enforce independent statement and branch coverage gates per package."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.config import CoverageGroup, load_config

ROOT = Path(__file__).resolve().parents[1]


def evaluate(report: dict[str, Any], groups: list[CoverageGroup]) -> list[str]:
    failures: list[str] = []
    for group in groups:
        selected = [
            item["summary"]
            for name, item in report["files"].items()
            if any(name.replace("\\", "/").startswith(prefix) for prefix in group["prefixes"])
        ]
        if not selected or not sum(item["num_statements"] for item in selected):
            failures.append(f"{group['name']}: no measured statements")
            continue
        for label, covered, total, minimum in (
            ("line", "covered_lines", "num_statements", group["line_min"]),
            ("branch", "covered_branches", "num_branches", group["branch_min"]),
        ):
            denominator = sum(item[total] for item in selected)
            percentage = (
                100 * sum(item[covered] for item in selected) / denominator
                if denominator
                else 100.0
            )
            print(f"{group['name']} {label}: {percentage:.2f}% (required {minimum}%)")
            if percentage < minimum:
                failures.append(f"{group['name']} {label}: {percentage:.2f}% < {minimum}%")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--group", action="append")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        groups = load_config(ROOT)["coverage_groups"]
        if args.group:
            unknown = set(args.group) - {group["name"] for group in groups}
            if unknown:
                raise ValueError("Unknown coverage group")
            groups = [group for group in groups if group["name"] in args.group]
        failures = evaluate(report, groups)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Invalid coverage report: {error}")
        return 1
    for failure in failures:
        print(f"FAIL: {failure}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
