"""Time helpers: day/week windows and rrule cadence checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apollo.tools.clock import Clock


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse an ISO-8601 string (or pass a datetime through); naive → UTC."""
    if value is None or isinstance(value, datetime):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def start_of_day(clock: Clock, moment: datetime | None = None) -> datetime:
    local = clock.local(moment)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(clock: Clock, moment: datetime | None = None) -> datetime:
    return start_of_day(clock, moment) + timedelta(days=1)


def start_of_week(clock: Clock, moment: datetime | None = None) -> datetime:
    """Monday 00:00 local."""
    start = start_of_day(clock, moment)
    return start - timedelta(days=start.weekday())


def day_window(clock: Clock, moment: datetime | None = None) -> tuple[datetime, datetime]:
    return start_of_day(clock, moment), end_of_day(clock, moment)


def week_window(clock: Clock, moment: datetime | None = None) -> tuple[datetime, datetime]:
    start = start_of_week(clock, moment)
    return start, start + timedelta(days=7)


def month_window(clock: Clock, moment: datetime | None = None) -> tuple[datetime, datetime]:
    local = clock.local(moment)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def is_due(rrule: str, moment: datetime) -> bool:
    """Very small rrule evaluator for the cadences Apollo seeds (DAILY/WEEKLY)."""
    rule = (rrule or "").upper()
    if "FREQ=DAILY" in rule:
        return True
    if "FREQ=WEEKLY" in rule:
        return moment.weekday() == _weekday(rule)
    return False


def _weekday(rule: str) -> int:
    names = {
        "MO": 0,
        "TU": 1,
        "WE": 2,
        "TH": 3,
        "FR": 4,
        "SA": 5,
        "SU": 6,
    }
    for token, index in names.items():
        if f"BYDAY={token}" in rule or f"BYDAY={token}," in rule:
            return index
    return 0


def cadence_days(cadence: str | None) -> float:
    """Parse simple cadences like ``3x/week`` into an average day gap."""
    if not cadence:
        return 7.0
    text = cadence.lower().strip()
    try:
        if "x/week" in text or "/week" in text:
            times = float(text.split("x")[0].split("/")[0].strip())
            return 7.0 / max(times, 0.1)
        if "x/month" in text or "/month" in text:
            times = float(text.split("x")[0].split("/")[0].strip())
            return 30.0 / max(times, 0.1)
        if text == "daily":
            return 1.0
        if text == "weekly":
            return 7.0
    except ValueError:
        return 7.0
    return 7.0
