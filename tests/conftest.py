"""Isolated filesystem and deterministic clock fixtures."""

import os
from pathlib import Path

import pytest

from tests.support.clock import FakeClock

os.environ.setdefault(
    "HYPOTHESIS_STORAGE_DIRECTORY",
    str(Path(__file__).resolve().parents[1] / ".artifacts/hypothesis"),
)


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    for name in ("personas", "skills", "memory", "compositions"):
        (root / name).mkdir(parents=True)
    return root
