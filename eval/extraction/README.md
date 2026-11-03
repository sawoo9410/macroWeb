# eval/extraction — 추출 평가셋 (Phase 2 DoD · PLAN §6.3, §6.2.4)

30개 Story(한국어 15 · 영어 15, 모든 LLM 층 포함)에 사람이 claim 을 라벨하고, 파이프라인이 뽑은 claim 과 비교한다.
프롬프트를 바꾸면 `make eval-extract` 가 회귀를 잡고, 같은 라벨로 §6.2.4 모델 라우팅 실험(Haiku vs Sonnet)을 채점한다.

## 파일
- `stories.jsonl` — 선택된 Story 목록(id·소스·층·언어·제목·URL·본문 길이). **본문은 저장소에 넣지 않는다**(로컬 DB 에만).
- `labels/<story_id>.yaml` — 라벨 파일. `labeler` 가 `null` 이면 채점에서 빠진다.
- `results/<날짜>-<db|small|mid|large>.json` — 채점 결과.

## 사용법
```bash
uv run macroweb eval extract build          # 30개 선택 + 라벨 템플릿 생성 (이미 있으면 유지; 다시 뽑으려면 --force)
uv run macroweb eval extract status         # 층별 라벨 진행률
uv run macroweb eval extract show st-…      # 라벨할 Story 의 제목·URL·본문(DB) 출력
uv run macroweb eval extract score          # DB 의 claim 과 비교 (= make eval-extract)
uv run macroweb eval extract score --tier small   # 라우팅 실험: 해당 등급의 ledger 결과(extraction.result_json)와 비교
```

## 라벨 규칙 (한 Story 에 3–8분)
1. `show` 로 본문을 읽고, **원문 문장 그대로** 검증 가능한 사실을 한 항목에 하나씩 적는다(원자적). 요약·해석·추론은 쓰지 않는다.
2. 숫자는 `value`/`unit` 으로 분리한다(`3.75` + `"%"`, `1.9` + `조원`, `18.9` + `"% YoY"`). 기간(QoQ/YoY)은 unit 에.
3. 날짜는 원문에 적힌 것만 `time_ref` 에(ISO). 없으면 `null`.
4. "관계자·소식통" 인용은 `anonymous_source: true`. 전망·예상은 `type: forecast`, 직접 인용은 `quote`, 누가 뭐라 했다는 `attribution`.
5. 기사가 명시하지 않은 사실·숫자는 만들지 않는다. 애매하면 `notes` 에 적고 넘어간다.
6. 다 적었으면 `labeler: sangwoo` 로 바꾼다. 층당 10개는 상우가, 나머지는 Opus 추출을 정답으로 쓰고 3개만 스팟 체크(§6.2.4; `labeler: opus`).

## 채점 방식 (`src/macroweb/eval/extraction.py`)
- claim 매칭: 텍스트 토큰(한글 2-gram·영문 단어) Jaccard ≥ 0.5 로 1:1 탐욕 매칭. 숫자 라벨은 값이 ±1 % 안이면 텍스트가 조금 달라도 매칭.
- 지표: 층별 micro P/R/F1, Story 평균 F1, **수치 오류율**(텍스트로 매칭됐는데 값이 없거나 다른 숫자 claim 비율).
- 판정(§6.2.4): claim F1 격차 ≥ 0.10 또는 수치 오류율 격차 ≥ 5%p 인 층만 상위 모델 배정 → ADR 로 고정.
