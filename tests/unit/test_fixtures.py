"""Validate time control and filesystem fixture isolation."""

from datetime import timedelta
from pathlib import Path

import pytest

from tests.support.clock import FakeClock


def test_manual_clock(fake_clock: FakeClock) -> None:
    before = fake_clock.now()
    fake_clock.advance(2.5)
    assert fake_clock.monotonic() == 2.5
    assert fake_clock.now() == before + timedelta(seconds=2.5)


@pytest.mark.parametrize("seconds", [-1, float("inf"), float("nan")])
def test_clock_rejects_invalid_advance(fake_clock: FakeClock, seconds: float) -> None:
    with pytest.raises(ValueError):
        fake_clock.advance(seconds)
    assert fake_clock.monotonic() == 0


def test_vault_is_temporary(vault_dir: Path, tmp_path: Path) -> None:
    assert vault_dir.is_relative_to(tmp_path)
    assert sorted(path.name for path in vault_dir.iterdir()) == [
        "compositions",
        "memory",
        "personas",
        "skills",
    ]
