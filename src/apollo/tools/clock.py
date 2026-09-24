"""Injectable clock. All scheduling/streak logic takes a clock, never ``datetime.now``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime: ...

    def local(self, moment: datetime | None = None) -> datetime: ...

    @property
    def tz(self) -> ZoneInfo: ...


class SystemClock:
    def __init__(self, tz: str = "UTC") -> None:
        self._tz = ZoneInfo(tz)

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    def now(self) -> datetime:
        return datetime.now(tz=self._tz)

    def local(self, moment: datetime | None = None) -> datetime:
        return (moment or self.now()).astimezone(self._tz)


class FrozenClock:
    """Deterministic clock for tests: ``FrozenClock("2026-01-01T09:00:00Z")``."""

    def __init__(self, moment: datetime | str, tz: str = "UTC") -> None:
        self._tz = ZoneInfo(tz)
        if isinstance(moment, str):
            moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        self._moment = moment

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    def now(self) -> datetime:
        return self._moment

    def local(self, moment: datetime | None = None) -> datetime:
        return (moment or self._moment).astimezone(self._tz)

    def advance(self, **kwargs: float) -> None:
        self._moment = self._moment + timedelta(**kwargs)
