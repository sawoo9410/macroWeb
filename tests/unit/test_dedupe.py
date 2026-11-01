from macroweb.collect.dedupe import canonical_url, hamming, simhash64, title_norm, tokens_for_simhash


def test_canonical_url_strips_tracking_and_amp() -> None:
    a = canonical_url("https://WWW.Example.com/news/123/amp/?utm_source=x&b=2&a=1#frag")
    assert a == "https://www.example.com/news/123?a=1&b=2"
    assert canonical_url("http://amp.cnn.com/cnn/2026/x.html") == "http://cnn.com/cnn/2026/x.html"
    assert canonical_url("https://x.com/a/") == "https://x.com/a"
    assert canonical_url("https://x.com/") == "https://x.com/"


def test_title_norm_and_simhash_locality() -> None:
    assert title_norm("[속보] 연준, 기준금리 동결") == "연준, 기준금리 동결"
    a = simhash64("연준, 기준금리 3.75~4.00%로 동결…두 명 인상 주장")
    b = simhash64("[속보] 연준 기준금리 3.75~4.00%로 동결… 두 명 인상 주장")
    c = simhash64("삼성전자, 3분기 영업이익 12조원 발표")
    assert hamming(a, b) <= 3
    assert hamming(a, c) > 15
    assert "연준" in "".join(tokens_for_simhash("연준 금리"))
    synd = simhash64("이형일, 경제현안간담회서 주택공급·일자리 논의(종합)")
    assert hamming(simhash64("이형일, 경제현안간담회서 주택공급·일자리 논의"), synd) == 0


def test_english_simhash_locality() -> None:
    a = simhash64("Fed holds rates steady, two dissents favor hike")
    b = simhash64("Fed holds rates steady; two dissents favor a hike")
    c = simhash64("Nvidia earnings beat estimates on data center demand")
    assert (
        hamming(a, b) <= 8
    )  # paraphrase: measured 6 with char-trigram simhash; story grouping uses <= 3 (exact/near-exact)
    assert hamming(a, c) > 15
    assert hamming(a, simhash64("\u201cFed holds rates steady, two dissents favor hike\u201d")) == 0
