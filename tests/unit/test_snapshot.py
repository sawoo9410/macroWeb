from datetime import UTC, datetime

from macroweb.collect.redact import redact_url
from macroweb.collect.snapshot import read_raw, save_raw


def test_save_raw_is_content_addressed_and_idempotent() -> None:
    ts = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)
    a = save_raw(
        "src", "https://x/feed", b"<rss/>", ext="xml", status=200, content_type="text/xml", fetched_at=ts
    )
    b = save_raw(
        "src", "https://x/feed", b"<rss/>", ext="xml", status=200, content_type="text/xml", fetched_at=ts
    )
    assert a.is_new and not b.is_new and a.path == b.path
    assert "2026/11/02" in str(a.path) and a.path.name.endswith(".xml.gz")
    assert read_raw(a.path) == b"<rss/>"
    assert a.path.with_name(f"{a.sha256}.meta.json").exists()


def test_redact_url() -> None:
    u = "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=abcdef123456&file_type=json"
    r = redact_url(u, ["abcdef123456"])
    assert "abcdef123456" not in r and "series_id=DGS10" in r and "api_key=%3Credacted%3E" in r
    e = redact_url(
        "https://ecos.bok.or.kr/api/StatisticSearch/SECRETKEY99/json/kr/1/10/722Y001/D/20260101/20260131/0101000",
        ["SECRETKEY99"],
    )
    assert "SECRETKEY99" not in e
