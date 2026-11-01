# MacroWeb — Makefile (PLAN §13.1). 모든 타깃은 uv 를 통해 .venv 안에서 실행한다.
UV ?= uv

.PHONY: help sync db-init doctor doctor-full test lint fmt cost status config-validate launchd-dryrun launchd-install launchd-uninstall eval-extract eval-verify precommit

help:
	@echo "make sync            - uv sync (.venv, Python 3.12)"
	@echo "make doctor          - 환경·DB·설정·훅 점검 (네트워크 제외, Phase 끝마다 통과 필수)"
	@echo "make doctor-full     - 소스 probe 포함 전체 점검"
	@echo "make test / lint / fmt"
	@echo "make cost            - config/models.yaml 단가로 월 비용 재계산"
	@echo "make launchd-dryrun  - plist 문법 + 임시 로드/launchctl print/언로드 (잡을 남기지 않음)"
	@echo "make launchd-install / launchd-uninstall"

sync:
	$(UV) sync

db-init:
	$(UV) run macroweb db init

doctor: db-init
	$(UV) run macroweb doctor --quick

doctor-full: db-init
	$(UV) run macroweb doctor

test:
	$(UV) run pytest -q

lint:
	$(UV) run ruff check src tests .claude/hooks
	$(UV) run ruff format --check src tests .claude/hooks
	$(UV) run mypy src

fmt:
	$(UV) run ruff format src tests .claude/hooks
	$(UV) run ruff check --fix src tests .claude/hooks

cost:
	$(UV) run macroweb cost

status:
	$(UV) run macroweb status

config-validate:
	$(UV) run macroweb config validate

launchd-dryrun:
	bash launchd/dryrun.sh

launchd-install:
	bash launchd/install.sh

launchd-uninstall:
	bash launchd/uninstall.sh

eval-extract:
	@echo "Phase 2 에서 구현: eval/extraction/ 30 Story 라벨 후 추출 회귀 (PLAN §6.3)"; exit 3

eval-verify:
	@echo "Phase 6 에서 구현: eval/verify/ 200 claim, F1 >= 0.85 (PLAN §7.5)"; exit 3

precommit:
	$(UV) run --with pre-commit pre-commit run --all-files
