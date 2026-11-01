"""Adaptive per-source fetch interval (PLAN §0.3 수집 주기):
interval = clamp(0.5 × feed window, 15 min, 6 h); event mode (confirmed calendar event ±2 h) puts T0 sources on
10 min. The 30-minute launchd tick only runs sources whose `next_due_at` has passed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from macroweb.config import CalendarEvent

MIN_INTERVAL_S = 15 * 60
MAX_INTERVAL_S = 6 * 3600
EVENT_INTERVAL_S = 10 * 60
EVENT_WINDOW = timedelta(hours=2)
DEFAULT_INTERVAL_BY_KIND = {
    "rss": 3600,
    "html": 2 * 3600,
    "api": 3600,
    "json": 3600,
    "pdf": 6 * 3600,
    "playwright": 2 * 3600,
}
KST = ZoneInfo("Asia/Seoul")


def compute_interval(feed_window_s: int | None, kind: str, tier: int) -> int:
    if feed_window_s and feed_window_s > 0:
        return int(min(MAX_INTERVAL_S, max(MIN_INTERVAL_S, feed_window_s * 0.5)))
    base = DEFAULT_INTERVAL_BY_KIND.get(kind, 3600)
    if tier == 0 and kind in ("rss", "html"):
        base = min(base, 3600)  # primary-source pages: at least hourly
    return base


def event_datetime(ev: CalendarEvent) -> datetime | None:
    if ev.status != "confirmed" or not ev.date or "TBD" in ev.date:
        return None
    hh, mm = 9, 0
    if ev.time_kst:
        head = ev.time_kst.strip()[:5]
        if len(head) == 5 and head[2] == ":":
            try:
                hh, mm = int(head[:2]), int(head[3:])
            except ValueError:
                hh, mm = 9, 0
    try:
        local = datetime.fromisoformat(ev.date).replace(hour=hh, minute=mm, tzinfo=KST)
    except ValueError:
        return None
    if ev.time_kst and "익일" in ev.time_kst:
        local += timedelta(days=1)
    return local.astimezone(UTC)


def event_mode_active(now: datetime, events: list[CalendarEvent]) -> bool:
    for ev in events:
        dt = event_datetime(ev)
        if dt is not None and abs(now - dt) <= EVENT_WINDOW:
            return True
    return False


def next_due(now: datetime, interval_s: int, tier: int, event_active: bool) -> datetime:
    if event_active and tier == 0:
        interval_s = min(interval_s, EVENT_INTERVAL_S)
    return now + timedelta(seconds=interval_s)


def is_due(next_due_at: str | None, now: datetime) -> bool:
    if not next_due_at:
        return True
    try:
        due = datetime.fromisoformat(next_due_at)
    except ValueError:
        return True
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return due <= now
