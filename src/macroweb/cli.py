"""`macroweb` CLI (typer). Every pipeline stage is an independent, idempotent subcommand (PLAN §0.1-6).
Stages that belong to a later Phase exist as stubs that exit 3 and name the Phase (PLAN §14)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from macroweb import __version__
from macroweb import phase as phase_mod
from macroweb.paths import ROOT, db_path

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="거미줄 (MacroWeb) — PLAN.md 가 단일 진실원"
)
db_app = typer.Typer(help="SQLite 생성·점검·마이그레이션", no_args_is_help=True)
config_app = typer.Typer(help="config/·prompts/ 스키마 검증", no_args_is_help=True)
source_app = typer.Typer(help="소스 레지스트리 (config/sources.yaml)", no_args_is_help=True)
phase_app = typer.Typer(help="Phase / DoD 상태 (docs/phase_status.json)", no_args_is_help=True)
market_app = typer.Typer(help="market 테이블 조회 (지표·가격, S-DATA)", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(config_app, name="config")
app.add_typer(source_app, name="source")
app.add_typer(phase_app, name="phase")
app.add_typer(market_app, name="market")
console = Console()

STAGE_PHASE = {
    "normalize": 1,
    "extract": 2,
    "verify": 2,
    "digest": 2,
    "graph": 3,
    "quality": 3,
    "weekly": 4,
    "monthly": 7,
}


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"macroweb {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", callback=_version_cb, is_eager=True, help="버전 출력"),
) -> None:
    """거미줄 (MacroWeb)."""


# --- doctor / cost / status / notify ---------------------------------------------------------------
@app.command()
def doctor(
    quick: bool = typer.Option(False, "--quick", help="네트워크 probe 생략 (훅·pre-commit 용)"),
    json_out: bool = typer.Option(False, "--json", help="JSON 출력"),
) -> None:
    """환경·DB·설정·훅·키 존재·디스크·launchd·비용 캡 점검. FAIL 이 하나라도 있으면 exit 1."""
    from macroweb.doctor import run_doctor, worst

    checks = run_doctor(quick=quick)
    w = worst(checks)
    if json_out:
        typer.echo(
            json.dumps({"worst": w, "checks": [c.as_dict() for c in checks]}, ensure_ascii=False, indent=2)
        )
    else:
        table = Table(title=f"macroweb doctor ({'quick' if quick else 'full'}) — overall {w}")
        table.add_column("check")
        table.add_column("status")
        table.add_column("detail", overflow="fold")
        colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red", "INFO": "cyan"}
        for c in checks:
            table.add_row(c.name, f"[{colors[c.status]}]{c.status}[/]", c.detail)
        console.print(table)
        counts = {s: sum(1 for c in checks if c.status == s) for s in ("PASS", "WARN", "FAIL", "INFO")}
        console.print(" · ".join(f"{k} {v}" for k, v in counts.items()))
    raise typer.Exit(1 if w == "FAIL" else 0)


@app.command()
def cost(json_out: bool = typer.Option(False, "--json")) -> None:
    """config/models.yaml 단가 × config/cost_workload.yaml 물량 → 월 비용 추정 (PLAN §16.4)."""
    from macroweb.cost import estimate

    est = estimate()
    if json_out:
        typer.echo(json.dumps(est.as_dict(), ensure_ascii=False, indent=2))
        return
    table = Table(
        title=f"월 비용 추정 (단가 {est.prices_updated}, weekly={est.weekly_runner_mode}, track_a={est.track_a_runner_mode})"
    )
    table.add_column("job")
    table.add_column("tier")
    table.add_column("batch")
    table.add_column("group")
    table.add_column("USD/월", justify="right")
    for line in est.lines:
        table.add_row(
            line.name, line.tier, "✓" if line.batch else "", line.group or "", f"{line.monthly_usd:.2f}"
        )
    console.print(table)
    console.print(
        f"API 합계 ≈ ${est.api_total_usd:.2f}/월 (캡 ${est.cap_usd:.0f}, {est.cap_pct or 0:.0f}%) · "
        f"구독으로 흡수 ≈ ${est.subscription_equivalent_usd:.2f}/월 상당 — 약 {est.subscription_calls_per_day:.0f}호출/일, "
        f"{est.subscription_tokens_per_day / 1e6:.1f}M 토큰/일(하네스 오버헤드 포함) · 단가 출처: {est.price_source}"
    )


@app.command()
def status(limit: int = typer.Option(10, help="최근 run 수")) -> None:
    """Phase 요약 + 최근 run + 이번 달 비용."""
    from macroweb.db import repo

    for line in phase_mod.summary_lines():
        console.print(line)
    p = db_path()
    if not p.exists():
        console.print(f"[yellow]DB 없음: {p} (make db-init)[/]")
        return
    conn = repo.connect(p)
    try:
        runs = repo.recent_runs(conn, limit)
        console.print(f"이번 달 비용(run.cost_usd 합): ${repo.month_cost_usd(conn):.2f}")
        if not runs:
            console.print("run 기록 없음")
            return
        table = Table(title="recent runs")
        for col in ("id", "job", "started_at", "ended_at", "status", "tokens_in", "tokens_out", "cost_usd"):
            table.add_column(col)
        for r in runs:
            table.add_row(
                *(
                    str(r[c])
                    for c in (
                        "id",
                        "job",
                        "started_at",
                        "ended_at",
                        "status",
                        "tokens_in",
                        "tokens_out",
                        "cost_usd",
                    )
                )
            )
        console.print(table)
    finally:
        conn.close()


@app.command()
def notify(
    level: str = typer.Option("info", help="info|warn|error"),
    job: str = typer.Option("manual"),
    message: str | None = typer.Option(None, "--message", "-m"),
    tail: int = typer.Option(0, help="logs/<job>.err.log 마지막 N줄 첨부"),
    rerun: str | None = typer.Option(None, help="재실행 명령어 (실패 알림에 포함)"),
) -> None:
    """stdout + macOS 알림 + (토큰 있으면) 텔레그램."""
    from macroweb.publish.notify import notify as _notify

    res = _notify(level, job, message, tail, rerun)
    console.print(f"[dim]{res}[/]")


# --- db ---------------------------------------------------------------------------------------------
@db_app.command("init")
def db_init() -> None:
    """DB 생성(없으면) + 미적용 마이그레이션 적용. 여러 번 실행해도 안전."""
    from macroweb.db import repo

    info = repo.init_db()
    console.print(json.dumps(info, ensure_ascii=False, indent=2))


@db_app.command("check")
def db_check() -> None:
    """PRAGMA integrity_check + schema_version."""
    from macroweb.db import repo

    p = db_path()
    if not p.exists():
        console.print(f"[red]DB 없음: {p}[/]")
        raise typer.Exit(1)
    conn = repo.connect(p)
    try:
        ic = repo.integrity_check(conn)
        console.print(
            f"integrity_check={ic} schema_version={repo.schema_version(conn)} tables={len(repo.table_names(conn))}"
        )
        raise typer.Exit(0 if ic == "ok" else 1)
    finally:
        conn.close()


@db_app.command("migrate")
def db_migrate() -> None:
    """미적용 migrations/NNNN_*.sql 적용 (init 과 동일 경로)."""
    db_init()


# --- config -----------------------------------------------------------------------------------------
@config_app.command("validate")
def config_validate(path: Path | None = typer.Option(None, "--path", help="한 파일만 검증")) -> None:
    """config/*.yaml 과 prompts/**/v*.md 를 스키마로 검증. 실패 시 exit 1."""
    from macroweb.config import validate_all

    results = validate_all(path)
    bad = [r for r in results if not r.ok]
    for r in results:
        mark = "[green]ok[/]" if r.ok else "[red]FAIL[/]"
        console.print(f"{mark} {r.name}: {r.message}")
    raise typer.Exit(1 if bad else 0)


@config_app.command("models")
def config_models() -> None:
    """모델 등급·ID·단가 요약."""
    from macroweb.config import load_models

    cfg = load_models()
    table = Table(title=f"config/models.yaml (updated {cfg.updated})")
    for col in ("tier", "alias", "model id", "in $/M", "out $/M", "cache read $/M"):
        table.add_column(col)
    for name, t in cfg.tiers.items():
        table.add_row(name, t.alias, t.id, f"{t.input}", f"{t.output}", f"{t.cache_read}")
    console.print(table)
    console.print(
        f"batch_discount={cfg.batch_discount} · monthly_cap=${cfg.budget.monthly_cap_usd} · weekly_runner={cfg.weekly_runner.mode}"
    )


# --- source -----------------------------------------------------------------------------------------
@source_app.command("list")
def source_list(enabled: bool = typer.Option(False, "--enabled", help="enabled 만")) -> None:
    from macroweb.collect.registry import list_sources

    table = Table(title="config/sources.yaml")
    for col in ("id", "tier", "kind", "stratum", "enabled", "url"):
        table.add_column(col, overflow="fold")
    for s in list_sources(enabled_only=enabled):
        table.add_row(s.id, f"T{s.tier}", s.kind, s.stratum or "", "✓" if s.enabled else "", s.url)
    console.print(table)


@source_app.command("probe")
def source_probe(
    source_id: str | None = typer.Argument(None, help="소스 id (생략 + --all 이면 전부)"),
    all_: bool = typer.Option(False, "--all"),
    include_disabled: bool = typer.Option(False, "--include-disabled"),
    markdown: bool = typer.Option(False, "--markdown"),
    out: Path | None = typer.Option(None, "--out", help="결과 md 저장 경로"),
) -> None:
    """실제 HTTP 요청으로 URL 생존 확인 (키 없이, 일반 UA, 도메인당 2초 간격)."""
    from macroweb.collect.registry import list_sources, probe_all, probe_markdown, probe_source

    if source_id:
        matches = [s for s in list_sources() if s.id == source_id]
        if not matches:
            console.print(f"[red]unknown source id {source_id}[/]")
            raise typer.Exit(1)
        results = [probe_source(matches[0])]
    elif all_:
        results = probe_all(enabled_only=not include_disabled)
    else:
        console.print("source id 또는 --all 을 지정하세요")
        raise typer.Exit(2)
    text = probe_markdown(results)
    if out:
        out.write_text(text + "\n", encoding="utf-8")
        console.print(f"saved {out}")
    if markdown or not out:
        console.print(text)
    bad = [r for r in results if not r.ok]
    console.print(f"{len(results) - len(bad)}/{len(results)} reachable")
    raise typer.Exit(1 if len(results) == len(bad) else 0)


@source_app.command("capture")
def source_capture(
    source_id: str | None = typer.Argument(None, help="소스 id (생략 + --all 이면 enabled 전부)"),
    all_: bool = typer.Option(False, "--all"),
    url: str | None = typer.Option(None, "--url", help="대체 URL (다중 요청 소스의 한 요청만)"),
) -> None:
    """실제 응답을 tests/fixtures/<id>/ 에 저장 (골든 테스트용, 쿠키·개인정보 없음)."""
    from macroweb.collect.fixtures import capture
    from macroweb.collect.http import make_client
    from macroweb.collect.politeness import DomainThrottle
    from macroweb.config import load_sources

    sources = load_sources().sources
    targets = [
        s for s in sources if (source_id and s.id == source_id) or (all_ and s.enabled and not s.auth_env)
    ]
    if not targets:
        console.print("[red]대상 소스가 없습니다[/]")
        raise typer.Exit(2)
    throttle = DomainThrottle()
    with make_client() as client:
        for s in targets:
            throttle.wait(url or s.url)
            try:
                p = capture(s, client, url)
                console.print(f"[green]ok[/] {s.id} -> {p.relative_to(ROOT)} ({p.stat().st_size} bytes)")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]ERR[/] {s.id}: {type(exc).__name__}: {str(exc)[:120]}")


@source_app.command("golden")
def source_golden(
    write: bool = typer.Option(False, "--write", help="골든 파일 생성/갱신 (없는 것만; --force 로 전부)"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """픽스처를 파서에 통과시켜 요약을 .golden.json 과 비교(기본) 또는 기록(--write)."""
    from macroweb.collect.golden import check_all, write_all

    if write:
        for path, status in write_all(force=force):
            console.print(f"{status:8s} {path.relative_to(ROOT)}")
        return
    failures = check_all()
    for name, msg in failures:
        console.print(f"[red]FAIL[/] {name}: {msg}")
    console.print(f"{'[green]golden ok[/]' if not failures else f'{len(failures)} failures'}")
    raise typer.Exit(1 if failures else 0)


# --- phase ------------------------------------------------------------------------------------------
@phase_app.command("show")
def phase_show(json_out: bool = typer.Option(False, "--json")) -> None:
    state = phase_mod.load()
    if json_out:
        typer.echo(json.dumps(state, ensure_ascii=False, indent=2))
        return
    for line in phase_mod.summary_lines(state):
        console.print(line)
    ph = phase_mod.current_phase(state)
    for item in phase_mod.items(state, ph):
        console.print(f"  [{'x' if item['done'] else ' '}] {item['id']}: {item['text']}", markup=False)


@phase_app.command("set")
def phase_set(
    target: str = typer.Argument(..., help="<phase>.<item_id>, 예: 0.make-doctor"),
    state: str = typer.Argument("done", help="done | todo"),
) -> None:
    ph, _, item = target.partition(".")
    updated = phase_mod.set_item(ph, item, state == "done")
    console.print(f"{ph}.{updated['id']} -> {'done' if updated['done'] else 'todo'}")


@phase_app.command("advance")
def phase_advance() -> None:
    """현재 Phase DoD 가 전부 done 이면 current_phase 를 +1."""
    st = phase_mod.load()
    ph = phase_mod.current_phase(st)
    todo = [i["id"] for i in phase_mod.items(st, ph) if not i["done"]]
    if todo:
        console.print(f"[red]Phase {ph} 미완료 DoD: {todo}[/]")
        raise typer.Exit(1)
    st["current_phase"] = int(ph) + 1
    phase_mod.save(st)
    console.print(f"current_phase -> {st['current_phase']}")


# --- pipeline stages (Phase-gated stubs) -------------------------------------------------------------
def _not_yet(stage: str) -> None:
    needed = STAGE_PHASE[stage]
    console.print(
        f"[yellow][{stage}] Phase {needed} 에서 구현된다 (PLAN.md §14). 현재 Phase {phase_mod.current_phase()}. "
        f"repo: {ROOT}[/]"
    )
    raise typer.Exit(3)


@app.command()
def collect(
    date: str | None = typer.Option(None, "--date", help="KST 날짜 YYYY-MM-DD (통계 파일 기준, 기본 오늘)"),
    source: list[str] | None = typer.Option(None, "--source", "-s", help="특정 소스만 (반복 가능)"),
    force: bool = typer.Option(False, "--force", help="next_due 를 무시하고 수집"),
    bodies: bool = typer.Option(True, "--bodies/--no-bodies", help="fetch_body 소스의 본문 수집"),
    body_limit: int = typer.Option(40, "--body-limit", help="틱당 본문 수집 상한"),
) -> None:
    """L1 수집 틱: 기한 도래 소스 → raw 스냅샷 → 기사·지표 저장 → 본문(robots 확인) → Story 그룹 → 일일 통계."""
    from macroweb.collect.pipeline import run_collect

    summary = run_collect(date, source_ids=source or None, force=force, bodies=bodies, body_limit=body_limit)
    console.print(summary.render())
    raise typer.Exit(summary.exit_code())


@app.command()
def stats(date: str | None = typer.Option(None, "--date", help="KST 날짜 (기본 오늘)")) -> None:
    """일일 수집 통계 md 재생성 (digests/collect-stats-<date>.md)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from macroweb.collect.stats import write_collect_stats
    from macroweb.db import repo

    day = date or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    repo.init_db()
    conn = repo.connect()
    try:
        console.print(str(write_collect_stats(conn, day)))
    finally:
        conn.close()


# --- market -----------------------------------------------------------------------------------------
@market_app.command("latest")
def market_latest(
    like: str | None = typer.Option(None, "--like", help="key LIKE 패턴 (예: 'UST:%', '%KRW%')"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """key 별 최신 값·기준일·보유 일수 (fact-checker 가 수치 대조에 쓴다)."""
    from macroweb.collect import store
    from macroweb.db import repo

    conn = repo.connect()
    try:
        rows = store.market_latest(conn, like)
    finally:
        conn.close()
    if json_out:
        console.print_json(json.dumps([dict(r) for r in rows], ensure_ascii=False))
        return
    table = Table(title=f"market — {len(rows)} keys")
    for col in ("key", "date", "value", "source", "days", "since"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            r["key"], r["date"], f"{r['value']:,.4f}", r["source"], str(r["n_days"]), r["first_date"]
        )
    console.print(table)


@market_app.command("get")
def market_get(
    key: str = typer.Argument(..., help="예: UST:10Y, NAVER:.SOX, ECB:USD_KRW_CROSS, KRAKEN:XBTUSD"),
    limit: int = typer.Option(30, "--limit", help="최근 n 개 (오래된 순 출력)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """한 key 의 최근 시계열."""
    from macroweb.collect import store
    from macroweb.db import repo

    conn = repo.connect()
    try:
        rows = store.market_series(conn, key, limit)
    finally:
        conn.close()
    if not rows:
        console.print(f"[yellow]no points for {key}[/] — `macroweb market latest` 로 key 목록 확인")
        raise typer.Exit(1)
    if json_out:
        console.print_json(json.dumps([dict(r) for r in rows], ensure_ascii=False))
        return
    for r in rows:
        console.print(f"{r['date']}  {r['value']:>14,.4f}  ({r['source']})")


@app.command()
def normalize(date: str | None = typer.Option(None, "--date")) -> None:
    """L2 정규화·Story 클러스터링 (Phase 1)."""
    _not_yet("normalize")


@app.command()
def extract(date: str | None = typer.Option(None, "--date")) -> None:
    """L3 추출: 배치 회수 + 실시간 처리 (Phase 2)."""
    _not_yet("extract")


@app.command()
def verify(date: str | None = typer.Option(None, "--date")) -> None:
    """L4 검증 신호·라벨 (Phase 2)."""
    _not_yet("verify")


@app.command()
def graph(action: str = typer.Argument("update", help="update|export-vault|propagate|path")) -> None:
    """L5 거미줄 갱신 (Phase 3)."""
    _not_yet("graph")


@app.command()
def digest(date: str | None = typer.Option(None, "--date")) -> None:
    """일일 다이제스트 10줄 (Phase 2)."""
    _not_yet("digest")


@app.command()
def quality(
    action: str = typer.Argument("run", help="run|apply"), week: str | None = typer.Option(None, "--week")
) -> None:
    """주간 데이터 품질 검토 Q1–Q7 (Phase 3 v1 / Phase 6 v2)."""
    _not_yet("quality")


@app.command()
def weekly(
    action: str = typer.Argument("run", help="pack|run"), week: str | None = typer.Option(None, "--week")
) -> None:
    """주간 합성: 데이터팩 + claude -p 헤드리스 편집국 (Phase 4, ADR-0002)."""
    _not_yet("weekly")


@app.command()
def monthly(month: str | None = typer.Option(None, "--month", help="YYYY-MM")) -> None:
    """월간 회고·학습 루프 (Phase 7)."""
    _not_yet("monthly")


if __name__ == "__main__":
    app()
