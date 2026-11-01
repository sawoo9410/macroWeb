# ADR-0005 — 키 없는 시장 데이터 경로: 재무부·ECB(T0) + Naver·Kraken(T3), API 의 robots 정책, key 명명

- 상태: 확정 · 날짜: 2026-11-02 · Phase 1 DoD `market-data`
- PLAN §0.3 "시장 데이터 = FRED·Stooq·FDR·ECOS" 와 충돌한다. **이 ADR 이 이긴다**: 키 없는 1차 경로를 아래 5개로 바꾸고, FRED·ECOS 는 키 입력 후 *추가* 되는 층으로 둔다. Stooq 는 뺀다. FDR(FinanceDataReader) 은 쓰지 않는다.

## 맥락
- `private/.env` 가 없어 FRED(Q16)·ECOS(Q17) 는 `skip … not set` 이다. Stooq 는 JavaScript 작업증명 봇 검사(ADR-0004-8). 그대로면 `market` 테이블에 금리·환율·지수가 하나도 없어 Phase 2 수치 검증(신호 4)과 시드 엔티티 `data_key` 가 붙을 곳이 없다.
- FDR 은 라이브러리 안에서 Naver/KRX/Yahoo 를 직접 긁는다 — 어댑터=순수 파서 + 픽스처 + 골든(ADR-0004-2·3) 규약 밖이고, 어떤 UA 로 어디를 치는지 우리가 통제하지 못한다.
- 2026-11-02 수집기 UA(`macroweb-collector/0.1`, 위장 없음)로 후보 엔드포인트를 실제 요청하고 **robots.txt 를 호스트별로 확인**했다.

## 선택지와 측정 (2026-11-02)
| 후보 | 응답 | robots.txt (`User-agent: *`) | 판정 |
|---|---|---|---|
| home.treasury.gov 일별 par 수익률 XML | 200 text/xml, 월 단위 | `Allow: /` | ✅ T0 채택 |
| data-api.ecb.europa.eu EXR csvdata | 200 text/csv, `D.USD+KRW+JPY+CNY.EUR.SP00.A` 다중 시리즈 | `/service/` 허용 (Drupal 기본 Disallow 만) | ✅ T0 채택 |
| api.stock.naver.com `/index/<sym>/price` (세계 지수) | 200 json, 60일/페이지, .SOX·.INX·.DJI·.IXIC·.VIX·.DXY 확인 | robots 없음(404) | ✅ T3 채택 |
| polling.finance.naver.com 국내 지수 실시간 | 200 json, `marketStatus`·`localTradedAt` 포함 | robots 없음(404) | ✅ T3 채택 — CLOSE 만 기록 |
| api.kraken.com OHLC 일봉 | 200 json, `since` 지원, `last` = 마지막 확정 캔들 | robots 없음(404) | ✅ T3 채택 |
| m.stock.naver.com `/api/index/KOSPI/price`·FX | 200 | **`Disallow: /`** | ❌ |
| fchart.stock.naver.com sise.nhn (KOSPI 일봉 XML) | 200 | **`Disallow: /`** | ❌ |
| query1.finance.yahoo.com chart | 200 | **`Disallow: /`** | ❌ |
| api.binance.com klines | 200 | **`Disallow: /`** | ❌ |
| api.exchange.coinbase.com candles | 200 | robots 401 → 규칙 불명 = 불허(robots.py 와 같은 보수 규칙) | ❌ |
| api.coingecko.com | — | `/api/v3` Disallow | ❌ |
| data.krx.co.kr getJsonData (GET) | HTML 안내 페이지(POST+Referer 필요) | 404 | ❌ 위장 없이는 불가 |
| stooq.com | JS 봇 검사 | — | ❌ (ADR-0004) |

## 결정
1. **API 소스도 robots.txt 를 따른다.** 본문 수집만 검사하던 ADR-0004-7 을 확장: 새 API 소스를 넣을 때 호스트 robots 를 손으로 확인하고 `sources.yaml.notes` 에 결과를 적는다(404 = 허용, `Disallow: /` 또는 4xx 불명 = 불허, UA 위장 없음). 자동 검사는 `source probe` 에 붙이는 것을 후속으로 둔다(지금은 기존 API 호스트가 전부 robots 없음이라 회귀 없음).
2. **소스 5개 추가** (`config/sources.yaml`, 전부 `S-DATA`, 키 없음): `treasury_yield_curve`(T0) · `ecb_exr`(T0) · `naver_world_index`(T3) · `naver_domestic_index`(T3) · `kraken_ohlc`(T3). 어댑터 = 순수 파서 5개(`collect/fetchers/api.py`), 픽스처·골든 각 1개, 다중 요청은 `plan_requests` 가 편다(재무부 전월+당월 2요청, Naver 심볼당 1요청 — `params.url_template`).
3. **key 명명** `<PROVIDER>:<SERIES>`: `UST:1M|3M|6M|1Y|2Y|5Y|10Y|30Y`, `ECB:<CUR>_EUR`, `NAVER:.SOX` 등 세계 지수는 Naver 심볼 그대로, `NAVER:KOSPI|KOSDAQ`, `KRAKEN:XBTUSD`. 같은 지표가 두 출처에서 오면(예: `UST:10Y` 와 키 입력 후 `FRED:DGS10`) **둘 다 저장**하고, 리포트·검증은 T0 원천(UST)을 우선한다.
4. **계산 시리즈는 이름에 드러낸다**: `UST:10Y2Y`·`UST:10Y3M`(스프레드, %p), `ECB:USD_KRW_CROSS`·`USD_JPY_CROSS`·`USD_CNY_CROSS`(= `<CUR>_EUR / USD_EUR`, 같은 14:15 CET 고시). 2026-10-30 교차환율 1,335.27 vs Naver 서울 종가 1,335.80 — 0.04% 차이. 서울 종가 USD/KRW 는 ECOS(Q17) 키 입력 후 `ECOS:…` 로 따로 들어온다.
5. **잠정치는 `market` 에 쓰지 않는다**: Naver 국내 지수는 `marketStatus == CLOSE` 일 때만 `localTradedAt` 날짜로 1점(실시간 엔드포인트라 과거치는 수집이 쌓이며 생긴다; 백필은 ECOS `802Y001` 키 입력 후). Kraken 은 `result.last` 이하 확정 캔들만(진행 중 캔들 제외). 재무부·ECB·Naver 세계 지수는 발표치만 온다.
6. **시드 `data_key` 갱신** (`seed/entities.yaml`): `sox` → `NAVER:.SOX`, `ust10y` → `UST:10Y`, `kospi` → `NAVER:KOSPI`. `usdkrw` 는 `ECOS:FX_USDKRW` 유지(키 입력 전까지는 `ECB:USD_KRW_CROSS` 로 대조), `oil` 은 `FRED:DCOILBRENTEU` 유지(키 없는 Brent 1차 출처를 찾지 못함 — EIA 는 키 필요).
7. **조회 CLI** `macroweb market latest [--like 'UST:%']` · `macroweb market get <key> --limit N` (PLAN 부록 fact-checker 도구 `macroweb market get *` 의 실체).

## 결과
- 2026-11-02 실수집(임시 `MACROWEB_DATA_DIR`): 요청 11건 전부 200, market 1,256점·26 key (UST 10 key × 21영업일, ECB 7 key × 85일, Naver 세계 6 × 60일, KOSPI·KOSDAQ 1일, BTC 89일). 두 번째 실행도 1,256 — 멱등. 테스트 131개 통과(골든 5개 추가), `make lint` 통과.
- `market-data` DoD 는 이 경로로 닫는다. FRED(15 시리즈: CPI·PCE·고용·WALCL·RRP·HY 스프레드·Brent·VIX 등)·ECOS 는 **키가 들어오면 어댑터 변경 없이 다음 틱부터** 추가된다(Q16·Q17 은 계속 열림).
- 후속: (a) S-DATA 일별 소스의 기본 주기를 1시간 → 6시간으로(스케줄러 `interval` 파라미터; 지금은 Naver 6요청/시간이라 예절 범위 안) (b) `source probe` 에 robots 자동 확인 (c) `tolerances.yaml` 에 UST↔FRED·ECB 교차↔ECOS 허용 오차.
