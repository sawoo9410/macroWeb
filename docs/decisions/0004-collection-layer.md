# ADR-0004 — L1 수집 계층: 스키마 확장, 어댑터·픽스처 규약, 키 없는 소스 정책

- 상태: 확정 · 날짜: 2026-11-02 · Phase 1 (sources-20 · raw-snapshot · dedupe · scheduler · collect-stats)

## 맥락
PLAN §4 는 소스 1개 = 어댑터 1개 + 픽스처 1개 + 골든 1개, raw 스냅샷 100%, URL/SimHash 중복제거, 30분 틱 + 소스별 적응 주기를 요구한다. 구현하면서 결정해야 했던 것들을 적는다.

## 결정
1. **스키마 v2 = migration `0002_collect.sql`** (schema.sql v1 은 손대지 않음). `source_stats` 에 스케줄 상태(`next_due_at`·`interval_s`·`feed_window_s`·`etag`·`last_modified`·실패 카운트), `article` 에 `summary`·`title_simhash`(16자리 hex — 64비트 값이 SQLite 부호 있는 INTEGER 를 넘을 수 있음)·`body_status`·`extra_json`, 새 테이블 `fetch_log`(일일 통계의 원천). `source` 에 `fetch_body`.
2. **어댑터 = 순수 파서** `bytes → ParseResult(items, market, feed_window_s)` (`collect/fetchers/`). 네트워크는 `collect/http.py` 한 곳(선언형 UA, ETag/If-Modified-Since, 8MB 상한). 다중 요청 소스(FRED 시리즈·ECOS 통계·HN 질의·Kalshi 시리즈)는 `plan_requests()` 가 펼친다.
3. **픽스처 = 실제 응답 그대로** `tests/fixtures/<id>/<date>.<ext>(.gz)` + `.meta.json`; 골든은 파서 요약(`.golden.json`: 건수·첫 3건·market 키). 300KB 넘는 피드는 gzip 보관. `macroweb source capture|golden` 로 갱신. 테스트는 네트워크 금지.
4. **raw 스냅샷은 내용 주소화** (`data/raw/YYYY/MM/DD/<sha256>.<ext>.gz` + meta). 같은 바이트는 다시 쓰지 않으므로 `collect` 재실행이 멱등. 키가 들어간 URL 은 `redact_url` 로 지운 뒤에만 meta·fetch_log·픽스처에 기록한다.
5. **중복제거 1·2단계**: URL 정규화(추적 파라미터·AMP·fragment·정렬) → 제목 SimHash(한글·CJK 는 문자 2-gram, 라틴은 문자 3-gram, 64비트). Story 그룹 임계 **해밍 ≤ 3** (PLAN §0.4 시작값). 측정: 재탕·따옴표·`(종합)` 접미는 0, 영문 패러프레이즈 ≈ 6, 무관 제목 ≈ 27–35. 즉 지금은 "같은 제목 전재"만 묶이고 의미 병합은 Phase 2 임베딩(코사인 ≥ 0.92)에서. 200쌍 라벨 보정 시 ≤ 6 을 후보로 본다. 전재 판정(`is_syndicated`) = 같은 parent_org 이거나 제목 완전 일치.
6. **스케줄**: `interval = clamp(0.5 × 피드 창, 15분, 6시간)`; 창을 모르는 html/api 는 종류별 기본(1–2시간, T0 는 ≤ 1시간); 실패 시 2^n 백오프(최대 1일), 3회 연속 실패 = `degraded`. 이벤트 모드(캘린더 `confirmed` 이벤트 ±2시간, T0 10분)는 코드만 들어가 있고 `calendar.yaml` 이 전부 `unverified` 라 아직 발동하지 않는다.
7. **본문 수집**은 `fetch_body: true` 인 비유료 소스만, robots.txt 허용 시, 틱당 40건, trafilatura. 피드가 본문을 품고 있으면(content:encoded > 1,500자) 그걸 쓴다. T1 한국 언론은 Phase 1 에서는 제목·리드만(robots·저작권 확인 후 결정).
8. **키·봇 정책**: FRED 는 키 없는 `fredgraph.csv` 가 수집기 UA 에 응답하지 않아(타임아웃) API 키 경로만 남김. Stooq 는 JavaScript 작업증명 봇 검사, BLS·Reddit·CME 는 403 — **UA 위장·우회 없음**(PLAN §0.1-7). 글로벌 지수 백업은 market-data 단계에서 FRED/FDR 로. 언어 감지는 한글 비율 휴리스틱(모델 없음).
9. Phase 1 어댑터 20+개(T0 9 · T1 8 · T2 5 · T3 3 · T4 1)가 픽스처·골든과 함께 들어갔다. ECOS·DART 어댑터는 키가 없어 픽스처 없이 구현만(키 입력 후 첫 수집에서 검증, QUESTIONS Q16·Q17).

## 결과
- `uv run macroweb collect` 가 30분 틱의 단일 진입점이며 `digests/collect-stats-<KST날짜>.md` 를 매번 덮어쓴다.
- 다음 보정 지점: Phase 1 끝 SimHash 임계(200쌍), 피드 창 실측값(`source_stats.feed_window_s`), Phase 2 에서 story 임베딩 병합.
