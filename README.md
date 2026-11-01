# 거미줄 (MacroWeb)

주간 거시·자금흐름 인사이트 자동화 파이프라인. 매일 수집·검증·관계 그래프 갱신, 매주 일요일 저녁 "거미줄 리포트" 발행.

- **단일 진실원:** [`PLAN.md`](PLAN.md) (v0.3). 세션 재시작 시 [`docs/PLAN_DIGEST.md`](docs/PLAN_DIGEST.md) 먼저.
- **현재 Phase:** `docs/phase_status.json` · 운영 규칙: [`CLAUDE.md`](CLAUDE.md)
- **설계 결정:** [`docs/decisions/`](docs/decisions/) · 미해결 질문: [`docs/QUESTIONS.md`](docs/QUESTIONS.md)
- **운영 절차:** [`docs/RUNBOOK.md`](docs/RUNBOOK.md)

## 빠른 시작

```bash
brew install uv                 # 1회
uv sync                         # .venv (Python 3.12) + 의존성
cp private/env.example private/.env   # 키 입력 (파일은 git 제외)
make doctor                     # 환경·DB·설정 점검
uv run macroweb --help
```

> 이 저장소의 산출물은 개인 학습·판단용이며 투자 자문이 아닙니다. 매수·매도·헤지 지시를 생성하지 않습니다.
