"""Version reporting and installation diagnostics for the initial CLI."""

import argparse
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

from reliclab_cli import __version__

OPTIONAL_PACKAGES = {"runtime": "reliclab-runtime", "ui": "reliclab-server"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relic", description="RelicLab development foundation")
    parser.add_argument("--version", action="version", version=f"reliclab {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="Inspect installed package versions")
    doctor.add_argument("--require", choices=tuple(OPTIONAL_PACKAGES))
    args = parser.parse_args(argv)
    missing: set[str] = set()
    for feature, package in {"core": "reliclab-core", **OPTIONAL_PACKAGES}.items():
        try:
            installed = version(package)
        except PackageNotFoundError:
            missing.add(feature)
            print(f"{package}: not installed")
        else:
            print(f"{package}: {installed}")
    print("Package presence does not imply implemented runtime or UI functionality.")
    if "core" in missing:
        parser.exit(1, "Required package reliclab-core is missing. Reinstall reliclab.\n")
    if args.require in missing:
        parser.exit(
            1, f'Optional package missing. Install with: pip install "reliclab[{args.require}]"\n'
        )
    return 0
