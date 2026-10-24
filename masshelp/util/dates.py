"""Date helpers. today() honors DEMO_TODAY so the demo date story stays consistent."""

from __future__ import annotations

from datetime import UTC, date, datetime

from masshelp.config import get_settings


def today() -> date:
    override = get_settings().demo_today
    return override or date.today()


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp (this SQLModel version requires aware datetimes)."""
    return datetime.now(UTC)


def age_on(dob: date, on: date) -> int:
    years = on.year - dob.year
    if (on.month, on.day) < (dob.month, dob.day):
        years -= 1
    return years


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None
