from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime


@dataclass
class FakeClock:
    now: datetime

    @classmethod
    def at(cls, hhmmss: str = "09:20:00") -> "FakeClock":
        hour, minute, second = [int(part) for part in hhmmss.split(":")]
        return cls(datetime(2026, 5, 8, hour, minute, second))

    def advance(self, seconds: int) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now

    @property
    def time(self) -> dtime:
        return self.now.time()

