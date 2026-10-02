"""A manually advanced clock for deterministic time-dependent tests."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import isfinite


@dataclass
class FakeClock:
    current: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    elapsed: float = 0.0

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.elapsed

    def advance(self, seconds: float) -> None:
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("Clock advance must be finite and non-negative")
        self.current += timedelta(seconds=seconds)
        self.elapsed += seconds
