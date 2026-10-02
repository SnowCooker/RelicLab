"""Isolated filesystem and deterministic clock fixtures."""

from pathlib import Path

import pytest

from tests.support.clock import FakeClock


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    for name in ("personas", "skills", "memory", "compositions"):
        (root / name).mkdir(parents=True)
    return root
