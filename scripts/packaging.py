"""Build distributions and verify isolated, offline wheel installations."""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

from scripts.config import load_config

ROOT = Path(__file__).resolve().parents[1]
COMBINATIONS = {
    "core": ("reliclab-core", ["reliclab"]),
    "cli": ("reliclab", ["reliclab", "reliclab_cli"]),
    "runtime": ("reliclab[runtime]", ["reliclab", "reliclab_cli", "reliclab_runtime"]),
    "ui": ("reliclab[ui]", ["reliclab", "reliclab_cli", "reliclab_server"]),
    "all": ("reliclab[all]", ["reliclab", "reliclab_cli", "reliclab_runtime", "reliclab_server"]),
}


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("uv is required for isolated wheel installation checks", file=sys.stderr)
        return 2
    output = ROOT / ".artifacts" / "packaging"
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(UV_OFFLINE="1", PIP_NO_INDEX="1", UV_PYTHON_DOWNLOADS="never", PYTHONUTF8="1")
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    uv_command = [uv, "--cache-dir", str(ROOT / ".uv-cache")]
    records: list[dict[str, object]] = []

    def run(command: list[str], cwd: Path, expected: int = 0) -> str:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        log_name = f"{len(records):02d}.log"
        (output / log_name).write_text(process.stdout, encoding="utf-8")
        records.append(
            {
                "command": command,
                "exit_code": process.returncode,
                "expected_exit_code": expected,
                "log": log_name,
            }
        )
        print(process.stdout, end="", flush=True)
        if process.returncode != expected:
            raise RuntimeError(
                f"Unexpected exit code {process.returncode}; see {output / log_name}"
            )
        return process.stdout

    success = False
    wheels: list[dict[str, object]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="reliclab-build-", dir=output) as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            requirements_file = root / "pylock.core.toml"
            run(
                [
                    *uv_command,
                    "export",
                    "--locked",
                    "--package",
                    "reliclab-core",
                    "--no-dev",
                    "--no-emit-workspace",
                    "--format",
                    "pylock.toml",
                    "--quiet",
                    "--output-file",
                    str(requirements_file),
                ],
                ROOT,
            )
            for package in load_config(ROOT)["packages"]:
                run(
                    [
                        sys.executable,
                        "-m",
                        "build",
                        "--no-isolation",
                        "--outdir",
                        str(wheelhouse),
                        str(ROOT / package["path"]),
                    ],
                    root,
                )
            for wheel in sorted(wheelhouse.glob("*.whl")):
                with zipfile.ZipFile(wheel) as archive:
                    names = archive.namelist()
                    if any(name.startswith(("docs/", "tests/", ".env", ".git/")) for name in names):
                        raise RuntimeError(f"Private files found in {wheel.name}")
                    metadata_path = next(
                        name for name in names if name.endswith(".dist-info/METADATA")
                    )
                    metadata = BytesParser().parsebytes(archive.read(metadata_path))
                    requirements = metadata.get_all("Requires-Dist", [])
                    if metadata["Name"] == "reliclab-core":
                        allowed = {"pydantic", "semver", "jsonschema", "pyyaml", "filelock"}
                        actual = {re.split(r"[<>=!;~ ]", item)[0].lower() for item in requirements}
                        if actual != allowed:
                            raise RuntimeError("Core wheel dependencies violate the allowlist")
                    wheels.append(
                        {
                            "file": wheel.name,
                            "name": metadata["Name"],
                            "requires": requirements,
                            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                        }
                    )
            for label, (requirement, modules) in COMBINATIONS.items():
                venv = root / label
                run([*uv_command, "venv", "--python", sys.executable, str(venv)], root)
                executable = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                # Artifact URLs avoid requiring index metadata in a fresh locked-sync cache.
                run(
                    [
                        *uv_command,
                        "pip",
                        "install",
                        "--python",
                        str(executable),
                        "--offline",
                        "--require-hashes",
                        "--no-deps",
                        "-r",
                        str(requirements_file),
                    ],
                    ROOT,
                )
                run(
                    [
                        *uv_command,
                        "pip",
                        "install",
                        "--python",
                        str(executable),
                        "--no-index",
                        "--find-links",
                        str(wheelhouse),
                        requirement,
                    ],
                    root,
                )
                absent = sorted(set(COMBINATIONS["all"][1]) - set(modules))
                probe = (
                    "import importlib, importlib.util, pathlib, sys; "
                    f"names = {modules!r}; absent = {absent!r}; "
                    "loaded = [importlib.import_module(name) for name in names]; "
                    "assert all(pathlib.Path(module.__file__).resolve().is_relative_to("
                    "pathlib.Path(sys.prefix).resolve()) for module in loaded); "
                    "assert all(importlib.util.find_spec(name) is None for name in absent); "
                    "assert all(importlib.util.find_spec(name) is None for name in "
                    "['fastapi', 'openai', 'anthropic']); "
                    "from reliclab.schema import validate_module, json_schema; "
                    "from jsonschema import Draft202012Validator; "
                    "asset = validate_module(dict(schema_version='1.0', kind='persona', "
                    "id='wheel-probe', version='1.0.0', name='Wheel probe', identity='Editor')); "
                    "Draft202012Validator(json_schema()).validate(asset.model_dump(mode='json')); "
                    "from reliclab.codec import parse_module, serialize_module; "
                    "assert parse_module(serialize_module(asset)) == asset; "
                    "from tempfile import TemporaryDirectory; "
                    "from reliclab.vault import Vault; "
                    "temporary = TemporaryDirectory(); vault = Vault(temporary.name); "
                    "snapshot = vault.create(asset); "
                    "assert vault.get(snapshot.key).content_hash == snapshot.content_hash; "
                    "from reliclab.resolve import resolve, CompositionLock; "
                    "request = validate_module(dict(schema_version='1.0', kind='composition', "
                    "id='probe-composition', version='1.0.0', name='Probe composition', "
                    "modules=dict(persona='wheel-probe@1'), render=dict(target='plain'))); "
                    "catalog = vault.snapshot(); graph = resolve(request, catalog); "
                    "lock = CompositionLock.from_json(graph.lock.to_json()); "
                    "assert resolve(request, catalog, lock=lock) == graph; "
                    "from reliclab.compose import compose; "
                    "context = compose(graph); "
                    "assert context.blocks[0].source_hash == snapshot.content_hash; "
                    "assert context.blocks[0].trust == 'reference'; "
                    "assert context.budget_report.status == 'not_evaluated'; "
                    "assert compose(graph).digest == context.digest; "
                    "vault.delete(snapshot.key, snapshot.content_hash); "
                    "assert vault.list() == (); temporary.cleanup(); "
                    "print({module.__name__: module.__version__ for module in loaded})"
                )
                run([str(executable), "-I", "-c", probe], root)
                if "reliclab_cli" in modules:
                    command = venv / ("Scripts/relic.exe" if os.name == "nt" else "bin/relic")
                    version = run([str(command), "--version"], root)
                    if "reliclab 0.1.0a1" not in version:
                        raise RuntimeError("Incorrect CLI version")
                    run([str(executable), "-I", "-m", "reliclab_cli", "doctor"], root)
                    if label == "cli":
                        for extra in ("runtime", "ui"):
                            result = run(
                                [str(command), "doctor", "--require", extra], root, expected=1
                            )
                            if f'pip install "reliclab[{extra}]"' not in result:
                                raise RuntimeError("Missing optional dependency guidance")
            for artifact in wheelhouse.iterdir():
                shutil.copy2(artifact, output / artifact.name)
            shutil.copy2(requirements_file, output / requirements_file.name)
        success = True
    except (OSError, RuntimeError) as error:
        print(f"Packaging check failed: {error}", file=sys.stderr)
    finally:
        (output / "report.json").write_text(
            json.dumps(
                {
                    "success": success,
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "wheels": wheels,
                    "commands": records,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
