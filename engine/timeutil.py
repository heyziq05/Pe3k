"""Small UTC timestamp helpers. Pe3k stores every timestamp as ``YYYY-MM-DDTHH:MM:SSZ``."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(ISO_FMT)


def now_iso() -> str:
    return to_iso(utcnow())


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, ISO_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def iso_ago(**kwargs) -> str:
    return to_iso(utcnow() - timedelta(**kwargs))


WINDOWS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def window_start(window: str | None, default: str = "24h") -> str | None:
    """Return the ISO start time for a named window, or ``None`` for ``all``."""
    if window == "all":
        return None
    delta = WINDOWS.get(window or default, WINDOWS[default])
    return to_iso(utcnow() - delta)


RANGE_LABELS = {
    "1h": "last hour", "6h": "last 6 hours", "24h": "last 24 hours", "7d": "last 7 days",
    "30d": "last 30 days", "all": "all time", "custom": "custom range",
}


def resolve_range(window: str | None, since: str | None = None, until: str | None = None) -> tuple[str | None, str | None, str]:
    """Turn a preset window or a custom ``since``/``until`` pair into ISO bounds.

    Returns ``(start, end, label)``; ``None`` means unbounded. Raises ``ValueError`` for bad input.
    """
    window = (window or "all").strip().lower()
    if window == "custom" or (window == "all" and (since or until)):
        start = parse_iso(since) if since else None
        end = parse_iso(until) if until else None
        if since and start is None:
            raise ValueError("'From' is not a valid date/time")
        if until and end is None:
            raise ValueError("'To' is not a valid date/time")
        if start and end and start > end:
            raise ValueError("'From' must be before 'To'")
        return (to_iso(start) if start else None, to_iso(end) if end else None, "custom")
    if window == "all":
        return None, None, "all"
    if window not in WINDOWS:
        raise ValueError(f"Unknown time range '{window}'. Use 1h, 6h, 24h, 7d, 30d, all or custom")
    return window_start(window), None, window
