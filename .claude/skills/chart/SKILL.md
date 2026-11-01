---
name: chart
description: 리포트 차트 규약 — 데이터 스펙(JSON) → matplotlib PNG. 색=부호 규칙, 한글 폰트, 출처·기준일 캡션, 파일명. 차트/그래프 PNG 를 만들 때 사용.
---
# 규약 (PLAN §8.8, §10.1 chart-maker)
- 입력 스펙: `{"id": "01-rates", "title": "...", "kind": "line|bar|heatmap|subgraph", "series": [{"name", "key(market)", "from", "to"}], "annotations": [...], "source": "FRED DGS10 · 기준일 YYYY-MM-DD"}`. 데이터는 `market` 테이블·데이터팩 값만 — 숫자를 만들지 않는다.
- 크기 1600×900 px (dpi 200, 8×4.5 in), 여백 넉넉히, 제목 ≤ 40자, 축 라벨 단위 명시(%, bp, 조원).
- 색: 이득/상승 `#2E7D32`(초록), 손해/하락 `#C62828`(빨강), 구조/중립 `#757575`(회색), 강조 1색 `#1565C0`. 한 차트에 4색 이내.
- 한글 폰트: `AppleGothic` → `NanumGothic` → 기본 순으로 `matplotlib.rcParams["font.family"]` 설정, `axes.unicode_minus=False`.
- 캡션(그림 아래 작은 글씨): 출처 · 기준일 · "[F]" 표시. 리포트 본문에는 `![caption](charts/$WEEK/01-rates.png)`.
- 서브그래프(kind=subgraph): networkx spring layout, 노드 색=타입, 엣지 색=부호, 굵기=weight×confidence, 노드 ≤ 25, 라벨은 canonical_name.
- 파일명 `charts/$WEEK/<nn>-<slug>.png`; 결과 목록 `data/weekly/$WEEK/chart_captions.json`.
- 실행 코드는 `uv run python` 으로, 스크립트는 `src/macroweb/publish/charts.py`(Phase 5) 또는 `data/weekly/$WEEK/charts/*.py`. 네트워크 호출 금지.
