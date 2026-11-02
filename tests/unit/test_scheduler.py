from datetime import UTC, datetime, timedelta

from macroweb.collect.scheduler import (
    EVENT_INTERVAL_S,
    MAX_INTERVAL_S,
    MIN_INTERVAL_S,
    compute_interval,
    event_mode_active,
    is_due,
    next_due,
)
from macroweb.config import CalendarEvent


def test_interval_clamps() -> None:
    assert compute_interval(600, "rss", 1) == MIN_INTERVAL_S
    assert compute_interval(7 * 24 * 3600, "rss", 1) == MAX_INTERVAL_S
    assert compute_interval(4 * 3600, "rss", 1) == 2 * 3600
    assert compute_interval(None, "html", 0) == 3600
    assert compute_interval(None, "api", 3) == 3600
    assert compute_interval(600, "api", 3, fixed=21600) == 21600  # explicit interval_s wins
    assert compute_interval(None, "api", 3, fixed=60) == MIN_INTERVAL_S  # floor still applies


def test_event_mode_and_due() -> None:
    now = datetime(2026, 12, 9, 19, 30, tzinfo=UTC)  # 04:30 KST on Dec 10 — 30 min after a 04:00 KST FOMC
    ev = CalendarEvent(
        id="x", name="FOMC", date="2026-12-10", time_kst="04:00", kind="fomc", status="confirmed", source="t"
    )
    assert event_mode_active(now, [ev])
    far = CalendarEvent(
        id="y", name="CPI", date="2026-12-10", time_kst="22:30", kind="data", status="confirmed", source="t"
    )
    assert not event_mode_active(now, [far])
    unverified = CalendarEvent(
        id="z", name="x", date="2026-12-10", time_kst="04:00", kind="fomc", status="unverified", source="t"
    )
    assert not event_mode_active(now, [unverified])
    assert next_due(now, 3600, 0, True) == now + timedelta(seconds=EVENT_INTERVAL_S)
    assert next_due(now, 3600, 1, True) == now + timedelta(seconds=3600)
    assert is_due(None, now) and is_due((now - timedelta(seconds=1)).isoformat(), now)
    assert not is_due((now + timedelta(minutes=5)).isoformat(), now)
