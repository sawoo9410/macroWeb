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


claim_app = typer.Typer(help="claim 조회 (Phase 2)", no_args_is_help=True)
app.add_typer(claim_app, name="claim")


@claim_app.command("get")
def claim_get(claim_id: str = typer.Argument(..., help="claim id (16 hex)")) -> None:
    """claim 한 건 + evidence + 소속 Story 를 JSON 으로 (fact-checker 가 쓰는 조회)."""
    from macroweb.db import repo

    conn = repo.connect()
    try:
        row = conn.execute("SELECT * FROM claim WHERE id = ?", (claim_id,)).fetchone()
        if not row:
            console.print(f"[red]no claim {claim_id}[/]")
            raise typer.Exit(1)
        ev = conn.execute(
            "SELECT e.kind, e.note, a.url, a.title, a.source_id, a.published_at FROM evidence e JOIN article a ON a.id = e.article_id WHERE e.claim_id = ?",
            (claim_id,),
        ).fetchall()
        st = conn.execute(
            "SELECT id, title_rep, n_independent, summary_ko FROM story WHERE id = ?", (row["story_id"],)
        ).fetchone()
        typer.echo(
            json.dumps(
                {"claim": dict(row), "evidence": [dict(e) for e in ev], "story": dict(st) if st else None},
                ensure_ascii=False,
                indent=1,
                default=str,
            )
        )
    finally:
        conn.close()


@claim_app.command("search")
def claim_search(
    query: str = typer.Argument(..., help="본문 부분 일치 (대소문자 무시)"),
    label: str | None = typer.Option(None, "--label"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """claim 검색 (텍스트 LIKE; Phase 3 에서 FTS/임베딩으로 교체)."""
    from macroweb.db import repo

    conn = repo.connect()
    try:
        sql = "SELECT id, type, label, confidence, impact, time_ref, text FROM claim WHERE status = 'active' AND lower(text) LIKE ?"
        params: list[object] = [f"%{query.lower()}%"]
        if label:
            sql += " AND label = ?"
            params.append(label)
        sql += " ORDER BY impact DESC, last_updated DESC LIMIT ?"
        params.append(limit)
        table = Table(title=f"claims matching {query!r}")
        for col in ("id", "type", "label", "conf", "impact", "time", "text"):
            table.add_column(col, overflow="fold")
        for r in conn.execute(sql, params).fetchall():
            table.add_row(
                r["id"],
                r["type"],
                r["label"] or "",
                f"{r['confidence'] or 0:.2f}",
                f"{r['impact'] or 0:.2f}",
                r["time_ref"] or "",
                r["text"][:90],
            )
        console.print(table)
    finally:
        conn.close()


@app.command("extractions")
def extractions(limit: int = typer.Option(20, "--limit")) -> None:
    """최근 추출 원장 (extraction 테이블)."""
    from macroweb.db import repo
    from macroweb.extract.runner import recent_extractions

    conn = repo.connect()
    try:
        table = Table(title="recent extractions")
        for col in ("story", "tier", "status", "model", "in", "out", "error", "title"):
            table.add_column(col, overflow="fold")
        for r in recent_extractions(conn, limit):
            table.add_row(
                r["story_id"],
                r["model_tier"],
                r["status"],
                r["model"] or "",
                str(r["tokens_in"] or ""),
                str(r["tokens_out"] or ""),
                (r["error"] or "")[:40],
                (r["title_rep"] or "")[:60],
            )
        console.print(table)
    finally:
        conn.close()


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


def _extract_run(*, limit: int | None, story: list[str] | None, force: bool, dry_run: bool) -> int:
    """Shared by `extract` and `tick`: select → fetch missing bodies → claude -p → persist. Returns the exit
    code (0 ok, 1 bad arguments, 2 subscription limit hit → caller backs off)."""
    from macroweb.config import load_extract, load_sources
    from macroweb.db import repo
    from macroweb.extract.bodies import ensure_bodies
    from macroweb.extract.runner import HeadlessExtractor
    from macroweb.extract.select import select_candidates

    if force and not story:
        console.print("[red]--force 는 --story 와 함께만 쓴다[/]")
        return 1
    repo.init_db()
    conn = repo.connect()
    try:
        ecfg = load_extract()
        cap = limit if limit is not None else ecfg.headless.calls_per_tick
        cands = select_candidates(
            conn,
            prompt_version=ecfg.prompt.version,
            limit=max(cap * 2, 10),
            cfg=ecfg,
            only=story or None,
            force=force,
        )
        if not story:
            from macroweb.extract.select import queued_escalations

            cands = queued_escalations(conn, prompt_version=ecfg.prompt.version, cfg=ecfg) + cands
        if dry_run:
            table = Table(title=f"extract --dry-run: {len(cands)} candidates (cap {cap})")
            for col in ("story_id", "tier", "stratum", "impact", "lang", "title"):
                table.add_column(col, overflow="fold")
            for c in cands[: cap * 2]:
                table.add_row(
                    c.story.story_id,
                    f"T{c.story.tier}",
                    c.story.stratum,
                    f"{c.impact:.2f}",
                    c.story.lang,
                    c.story.title[:70],
                )
            console.print(table)
            return 0
        cands, body_report = ensure_bodies(
            conn, cands, {s.id: s for s in load_sources().sources}, max_fetch=10
        )
        if body_report.attempted:
            console.print(
                f"bodies: fetched={body_report.fetched} robots={body_report.robots_disallow} failed={body_report.failed} dropped={len(body_report.still_empty)}"
            )
        run_id = repo.start_run(conn, "extract", {ecfg.prompt.name: f"v{ecfg.prompt.version}"})
        report = HeadlessExtractor(conn, extract_cfg=ecfg).run(cands, max_calls=cap)
        repo.finish_run(
            conn,
            run_id,
            "limit" if report.limit_hit else "ok",
            {k: v for k, v in vars(report).items()},
            tokens_in=report.tokens_in,
            tokens_out=report.tokens_out,
            model_tier="mixed",
            cost_usd=0.0,
        )
        console.print(report.render())
        return 2 if report.limit_hit else 0
    finally:
        conn.close()


@app.command()
def extract(
    date: str | None = typer.Option(None, "--date", help="KST 날짜 (기본 오늘)"),
    limit: int | None = typer.Option(
        None, "--limit", help="이번 실행 호출 상한 (기본 extract.yaml headless.calls_per_tick)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="선별 결과만 출력, 모델 호출 없음"),
    story: list[str] | None = typer.Option(None, "--story", help="특정 story_id 만"),
    force: bool = typer.Option(
        False,
        "--force",
        help="--story 와 함께: 이미 추출(성공·실패)된 Story 도 다시 보낸다 (claim id 는 내용 주소라 중복 없음)",
    ),
) -> None:
    """L3 추출 (Phase 2, ADR-0007): Story 선별 → claude -p(구독) → claim/entity 저장. 호출 상한·한도 가드 적용."""
    raise typer.Exit(_extract_run(limit=limit, story=story, force=force, dry_run=dry_run))


@app.command()
def tick(
    date: str | None = typer.Option(None, "--date", help="KST 날짜 (통계 파일 기준, 기본 오늘)"),
    extract_cap: int | None = typer.Option(
        None, "--extract-cap", help="이 틱의 추출 호출 상한 (기본 extract.yaml headless.calls_per_tick)"
    ),
    no_extract: bool = typer.Option(
        False, "--no-extract", help="수집만 (extract.yaml tick_extract 와 같은 효과)"
    ),
) -> None:
    """30분 틱 진입점(launchd): collect → extract(≤ calls_per_tick, 한도 가드) → verify(Phase 2 후반). 수집 실패만
    실패로 돌려준다 — 구독 한도 백오프는 정상 동작이라 exit 0."""
    from macroweb.collect.pipeline import run_collect
    from macroweb.config import load_extract

    summary = run_collect(date)
    console.print(summary.render())
    rc = summary.exit_code()
    if no_extract or not load_extract().headless.tick_extract:
        console.print("extract: skipped (tick_extract off)")
    else:
        try:
            erc = _extract_run(limit=extract_cap, story=None, force=False, dry_run=False)
        except Exception as exc:  # the model stage must never take the collector down with it
            console.print(f"[red]extract: {type(exc).__name__}: {exc}[/]")
            rc = rc or 1
        else:
            if erc == 2:
                console.print("extract: subscription limit — backing off (see logs/claude_limit.stamp)")
    try:
        console.print(_verify_run(day=date, since_hours=72, story=None, relabel=False).render())
    except Exception as exc:  # labelling is derived data; never fail the tick on it
        console.print(f"[red]verify: {type(exc).__name__}: {exc}[/]")
        rc = rc or 1
    try:
        console.print(f"digest: {_digest_run(date)}")
    except Exception as exc:
        console.print(f"[red]digest: {type(exc).__name__}: {exc}[/]")
        rc = rc or 1
    raise typer.Exit(rc)


def _digest_run(day: str | None) -> Path:
    """digests/<KST day>.md — rewritten on every tick (idempotent), closed by the last tick of the day."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from macroweb.db import repo
    from macroweb.digest.daily import write_digest

    kst_day = day or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    repo.init_db()
    conn = repo.connect()
    try:
        return write_digest(conn, kst_day)
    finally:
        conn.close()


def _verify_run(*, day: str | None, since_hours: int, story: list[str] | None, relabel: bool):  # type: ignore[no-untyped-def]
    """Shared by `verify` and `tick` (ADR-0009): deterministic v1 signals → confidence/label → review queue."""
    from macroweb.config import load_verify
    from macroweb.db import repo
    from macroweb.verify.run import run_verify

    repo.init_db()
    conn = repo.connect()
    try:
        run_id = repo.start_run(conn, "verify", {"verify": f"v{load_verify().version}"})
        report = run_verify(conn, since_hours=since_hours, story_ids=story or None, relabel=relabel, day=day)
        repo.finish_run(conn, run_id, "ok", report.as_dict())
        return report
    finally:
        conn.close()


eval_app = typer.Typer(help="평가셋 (Phase 2: 추출 30 Story · Phase 6: 검증 200 claim)", no_args_is_help=True)
app.add_typer(eval_app, name="eval")
eval_extract_app = typer.Typer(help="추출 평가셋 — eval/extraction/ (PLAN §6.3·§6.2.4)", no_args_is_help=True)
eval_app.add_typer(eval_extract_app, name="extract")


@eval_extract_app.command("build")
def eval_extract_build(
    force: bool = typer.Option(
        False, "--force", help="stories.jsonl 을 다시 뽑는다 (라벨 파일은 절대 덮어쓰지 않음)"
    ),
) -> None:
    """30개 Story(한/영 반반, 층별 할당) 선택 + labels/<story_id>.yaml 템플릿 생성."""
    from macroweb.db import repo
    from macroweb.eval.extraction import build, status

    conn = repo.connect()
    try:
        stories = build(conn, force=force)
    finally:
        conn.close()
    st = status()
    console.print(f"stories={len(stories)} labeled={st['labeled']} buckets={st['buckets']}")
    console.print(
        "다음: `uv run macroweb eval extract show <story_id>` 로 본문을 보고 labels/<story_id>.yaml 을 채운다 (README)."
    )


@eval_extract_app.command("status")
def eval_extract_status() -> None:
    """층별 라벨 진행률."""
    from macroweb.eval.extraction import status

    console.print_json(json.dumps(status(), ensure_ascii=False))


@eval_extract_app.command("show")
def eval_extract_show(story_id: str = typer.Argument(..., help="stories.jsonl 의 story_id")) -> None:
    """라벨할 Story 의 제목·URL·본문(DB) 을 출력한다 — 저장소에는 본문을 넣지 않는다."""
    from macroweb.db import repo
    from macroweb.eval.extraction import story_text

    conn = repo.connect()
    try:
        d = story_text(conn, story_id)
    finally:
        conn.close()
    if not d:
        console.print(f"[red]no story {story_id}[/]")
        raise typer.Exit(1)
    console.print(f"# {d['title_rep']}\n{d['source_id']} · {d['published_at']} · {d['url']}\n")
    console.print(d["text"])


@eval_extract_app.command("score")
def eval_extract_score(
    tier: str | None = typer.Option(
        None, "--tier", help="small|mid|large — 해당 등급의 ledger 결과와 비교 (라우팅 실험)"
    ),
    prompt_version: int | None = typer.Option(None, "--prompt-version"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """라벨(labeler 가 채워진 파일)과 추출 결과를 비교해 층별 P/R/F1·수치 오류율을 낸다. 결과는 eval/extraction/results/."""
    from macroweb.db import repo
    from macroweb.eval.extraction import score

    conn = repo.connect()
    try:
        report = score(conn, tier=tier, prompt_version=prompt_version)
    finally:
        conn.close()
    if json_out:
        console.print_json(json.dumps(report.as_dict(), ensure_ascii=False))
    else:
        console.print(report.render())
    if not report.stories:
        console.print("[yellow]채점할 라벨이 없다 — labels/*.yaml 의 labeler 와 claims 를 채운다 (Q20).[/]")
        raise typer.Exit(3)


@app.command()
def verify(
    date: str | None = typer.Option(None, "--date", help="review/<date>.md 의 날짜 (KST, 기본 오늘)"),
    since_hours: int = typer.Option(
        72, "--since-hours", help="이 시간 안에 추출·갱신된 claim 을 재검증 (라벨 없는 claim 은 항상 포함)"
    ),
    story: list[str] | None = typer.Option(None, "--story", help="특정 story_id 의 claim 만"),
    all_claims: bool = typer.Option(False, "--all", help="모든 active claim 재라벨 (idempotent)"),
) -> None:
    """L4 검증 v1 (ADR-0009): 신호 1·2·4·5·6 → confidence/라벨 → 고영향·저신뢰 claim 을 review 큐 + review/<date>.md 로."""
    console.print(_verify_run(day=date, since_hours=since_hours, story=story, relabel=all_claims).render())


graph_app = typer.Typer(
    help="L5 거미줄 (Phase 3, ADR-0010 v1): 시드·엣지 갱신·해소·전파·경로·diff·내보내기", no_args_is_help=True
)
app.add_typer(graph_app, name="graph")


def _graph_conn():  # type: ignore[no-untyped-def]
    from macroweb.db import repo

    repo.init_db()
    return repo.connect()


@graph_app.command("load-seed")
def graph_load_seed() -> None:
    """seed/entities.yaml·relations.yaml·persons/ → candidate 노드/엣지 (idempotent)."""
    from macroweb.graph.store import load_seed

    conn = _graph_conn()
    try:
        rep = load_seed(conn)
    finally:
        conn.close()
    console.print(
        f"seed: entities new/seen={rep.entities_new}/{rep.entities_seen} edges new/seen={rep.edges_new}/{rep.edges_seen} persons={rep.persons}"
    )
    for p in rep.problems:
        console.print(f"[yellow]  {p}[/]")


@graph_app.command("update")
def graph_update(
    since: str | None = typer.Option(None, "--since", help="이 시각(ISO) 이후 성공한 추출만"),
    no_resolve: bool = typer.Option(False, "--no-resolve", help="엔티티 해소(별칭 병합·승격) 건너뛰기"),
) -> None:
    """추출 relations → 엣지(evidence = 그 Story 의 claim) → 엔티티 해소 → 만료 처리."""
    from macroweb.graph.store import expire_edges, graph_counts, resolve_entities, update_from_extractions

    conn = _graph_conn()
    try:
        st = update_from_extractions(conn, since=since)
        console.print(
            f"edges inserted={st.inserted} reinforced={st.reinforced} entities_new={st.entities_new} "
            f"skipped: no_evidence={st.skipped_no_evidence} unknown_type={st.skipped_unknown_type} unresolved={st.skipped_unresolved}"
        )
        if not no_resolve:
            rr = resolve_entities(conn)
            console.print(
                f"resolve: merged={len(rr.merged)} promoted={len(rr.promoted)} counted={rr.counted}"
            )
        console.print(f"expired edges={expire_edges(conn)} · counts={graph_counts(conn)}")
    finally:
        conn.close()


@graph_app.command("resolve")
def graph_resolve() -> None:
    """별칭 완전 일치 병합 + Story 3개 이상 candidate → confirmed."""
    from macroweb.graph.store import resolve_entities

    conn = _graph_conn()
    try:
        rr = resolve_entities(conn)
    finally:
        conn.close()
    console.print(f"merged={rr.merged} promoted={rr.promoted} counted={rr.counted}")


@graph_app.command("stats")
def graph_stats(
    pair: tuple[str, str] | None = typer.Option(
        None, "--pair", help="market 키 두 개 (예: UST:10Y NAVER:.SOX)"
    ),
    all_computed: bool = typer.Option(False, "--all", help="origin=computed 시드 엣지 전부 재계산"),
    write: bool = typer.Option(False, "--write", help="결과를 엣지 r/lag 에 기록"),
) -> None:
    """통계 엣지 r/lag — 가격 데이터로 계산만 한다(추정 금지). 자료가 모자라면 그렇다고 말한다."""
    import json as _json

    from macroweb.graph.analysis import pair_stats
    from macroweb.graph.store import upsert_edge

    conn = _graph_conn()
    try:
        jobs: list[tuple[str, str, str | None, str | None, str | None]] = []
        if pair:
            jobs.append((pair[0], pair[1], None, None, None))
        if all_computed:
            for r in conn.execute(
                """SELECT r.src_eid, r.dst_eid, r.type, es.profile_json AS sp, ed.profile_json AS dp FROM relation r
                   JOIN entity es ON es.id = r.src_eid JOIN entity ed ON ed.id = r.dst_eid WHERE r.origin = 'computed'"""
            ):
                ks = (_json.loads(r["sp"] or "{}")).get("data_key")
                kd = (_json.loads(r["dp"] or "{}")).get("data_key")
                if ks and kd:
                    jobs.append((ks, kd, r["src_eid"], r["dst_eid"], r["type"]))
        if not jobs:
            console.print("[yellow]--pair A B 또는 --all 이 필요하다[/]")
            raise typer.Exit(1)
        for ka, kb, src, dst, rtype in jobs:
            ps = pair_stats(conn, ka, kb)
            console.print(f"{ka} → {kb}: n={ps.n} r={ps.r} lag={ps.lag_days} {ps.note}")
            if write and src and dst and rtype and ps.r is not None and not ps.note:
                upsert_edge(
                    conn,
                    src=src,
                    dst=dst,
                    rtype=rtype,
                    sign=1 if ps.r > 0 else -1,
                    weight=abs(ps.r),
                    confidence=min(1.0, ps.n / 250),
                    evidence_ids=[],
                    origin="computed",
                    story_id=None,
                    seen_at=__import__("datetime")
                    .datetime.now(__import__("datetime").UTC)
                    .isoformat(timespec="seconds"),
                    note=f"computed {ka}~{kb} n={ps.n}",
                    r=ps.r,
                    lag_days=ps.lag_days,
                )
                conn.commit()
    finally:
        conn.close()


@graph_app.command("propagate")
def graph_propagate(
    node: str = typer.Argument(..., help="충격 노드 id (예: fomc-2026-12-09)"),
    sign: int = typer.Option(1, "--sign", help="+1 / -1"),
    magnitude: float = typer.Option(1.0, "--magnitude"),
    as_of: str | None = typer.Option(None, "--as-of", help="YYYY-MM-DD 시간 슬라이스"),
    depth: int = typer.Option(3, "--depth"),
    floor: float = typer.Option(0.05, "--floor"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """충격 전파 v1 (PLAN §8.7): 1·2·3차 효과와 경로·evidence."""
    import json as _json

    from macroweb.graph.analysis import propagate
    from macroweb.graph.store import active_edges

    conn = _graph_conn()
    try:
        effects = propagate(
            active_edges(conn, as_of=as_of),
            node,
            sign=sign,
            magnitude=magnitude,
            max_depth=depth,
            floor=floor,
        )
    finally:
        conn.close()
    if json_out:
        console.print_json(_json.dumps([e.as_dict() for e in effects], ensure_ascii=False))
        return
    table = Table(
        title=f"propagate {node} sign={sign:+d} mag={magnitude} as_of={as_of or 'now'} → {len(effects)} effects"
    )
    for col in ("depth", "target", "sign", "magnitude", "path (nodes)", "evidence"):
        table.add_column(col, overflow="fold")
    for e in effects[:40]:
        table.add_row(
            str(e.depth),
            e.target,
            f"{e.sign:+d}",
            f"{e.magnitude:.3f}",
            " → ".join(e.nodes),
            str(len(e.evidence)),
        )
    console.print(table)


@graph_app.command("path")
def graph_path(
    src: str = typer.Argument(...),
    dst: str = typer.Argument(...),
    k: int = typer.Option(3, "--k"),
    as_of: str | None = typer.Option(None, "--as-of"),
) -> None:
    """사건→자산 연결 설명 경로 k개."""
    from macroweb.graph.analysis import k_paths
    from macroweb.graph.store import active_edges

    conn = _graph_conn()
    try:
        paths = k_paths(active_edges(conn, as_of=as_of), src, dst, k=k)
    finally:
        conn.close()
    if not paths:
        console.print(f"[yellow]no path {src} → {dst}[/]")
        raise typer.Exit(1)
    for p in paths:
        console.print(
            f"{p['hops']} hops · strength {p['strength']} · net sign {p['net_sign']:+d}: {' → '.join(p['nodes'])}"
        )


@graph_app.command("hubs")
def graph_hubs(
    top: int = typer.Option(10, "--top"), as_of: str | None = typer.Option(None, "--as-of")
) -> None:
    """가중 PageRank 허브 (이번 주 누가 중앙에 섰나)."""
    from macroweb.graph.analysis import hubs
    from macroweb.graph.store import active_edges

    conn = _graph_conn()
    try:
        for n, score in hubs(active_edges(conn, as_of=as_of), top=top):
            console.print(f"{score:.4f} {n}")
    finally:
        conn.close()


@graph_app.command("diff")
def graph_diff(week: str | None = typer.Option(None, "--week", help="ISO 주 (기본 이번 주)")) -> None:
    """주간 그래프 diff: 신규·강화·만료 엣지, 신규 엔티티, 스냅샷 저장."""
    import json as _json

    from macroweb.graph.analysis import iso_week, weekly_diff

    conn = _graph_conn()
    try:
        d = weekly_diff(conn, week or iso_week())
    finally:
        conn.close()
    console.print_json(_json.dumps(d.summary(), ensure_ascii=False))


@graph_app.command("export-vault")
def graph_export_vault(as_of: str | None = typer.Option(None, "--as-of")) -> None:
    """vault/entities/<type>/<id>.md + index.md (Obsidian 호환, wikilink = 엣지)."""
    from macroweb.graph.export import export_vault

    conn = _graph_conn()
    try:
        rep = export_vault(conn, as_of=as_of)
    finally:
        conn.close()
    console.print(f"vault: {rep.entities} entities → {rep.index}")


@graph_app.command("html")
def graph_html(
    week: str | None = typer.Option(None, "--week"), as_of: str | None = typer.Option(None, "--as-of")
) -> None:
    """charts/graph-<week>.html — cytoscape.js 뷰어(기준일 슬라이더·엣지 클릭 시 evidence)."""
    from macroweb.graph.analysis import iso_week
    from macroweb.graph.export import render_html

    conn = _graph_conn()
    try:
        console.print(str(render_html(conn, week or iso_week(), as_of=as_of)))
    finally:
        conn.close()


@graph_app.command("render")
def graph_render(
    week: str | None = typer.Option(None, "--week"),
    nodes: int = typer.Option(25, "--nodes"),
    as_of: str | None = typer.Option(None, "--as-of"),
) -> None:
    """charts/graph-<week>.png — 리포트용 서브그래프(노드 ≤ 25)."""
    from macroweb.graph.analysis import iso_week
    from macroweb.graph.export import render_png

    conn = _graph_conn()
    try:
        path = render_png(conn, week or iso_week(), max_nodes=nodes, as_of=as_of)
    finally:
        conn.close()
    console.print(str(path) if path else "[yellow]no active edges to render[/]")


@graph_app.command("counts")
def graph_counts_cmd() -> None:
    """엔티티·엣지 상태별 수."""
    from macroweb.graph.store import graph_counts

    conn = _graph_conn()
    try:
        console.print_json(json.dumps(graph_counts(conn), ensure_ascii=False))
    finally:
        conn.close()


@app.command()
def digest(
    date: str | None = typer.Option(None, "--date", help="KST 날짜 (기본 오늘)"),
    json_out: bool = typer.Option(False, "--json", help="채운 값만 JSON 으로"),
) -> None:
    """일일 다이제스트 10줄 (Phase 2): digests/<date>.md — DB·설정에서 잰 값만, 미구현 엔진은 그렇다고 쓴다."""
    if json_out:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from macroweb.db import repo
        from macroweb.digest.daily import build_digest, digest_json

        kst_day = date or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        conn = repo.connect()
        try:
            console.print(digest_json(build_digest(conn, kst_day)))
        finally:
            conn.close()
        return
    console.print(str(_digest_run(date)))


@app.command()
def quality(
    action: str = typer.Argument("run", help="run"),
    week: str | None = typer.Option(None, "--week", help="ISO 주 (기본 이번 주)"),
    no_apply: bool = typer.Option(False, "--no-apply", help="자동 처리(격리·만료·병합) 없이 보고만"),
) -> None:
    """주간 데이터 품질 검토 v1: Q1·Q2·Q4·Q6 결정론 검사 + 스코어카드 reports/quality/<week>.md (Q3·Q5·Q7 은 Phase 6)."""
    from macroweb.db import repo
    from macroweb.graph.analysis import iso_week
    from macroweb.quality.weekly import run_quality

    if action != "run":
        console.print(
            "[yellow]v1 은 `quality run` 만 있다 (apply 는 run 이 함께 한다; --no-apply 로 끈다)[/]"
        )
        raise typer.Exit(1)
    repo.init_db()
    conn = repo.connect()
    try:
        run_id = repo.start_run(conn, "quality")
        res = run_quality(conn, week or iso_week(), apply=not no_apply)
        repo.finish_run(conn, run_id, "ok", res.as_dict())
    finally:
        conn.close()
    console.print(res.scoreline())
    for a in res.actions:
        console.print(f"  - {a}")
    console.print(f"report: {res.report}")


weekly_app = typer.Typer(
    help="주간 편집국 (Phase 4 v1, ADR-0002/0010): 품질 → 데이터팩 → claude -p /weekly-report → 게이트 → 발행",
    no_args_is_help=True,
)
app.add_typer(weekly_app, name="weekly")


def _week_or_now(week: str | None) -> str:
    from macroweb.graph.analysis import iso_week

    return week or iso_week()


@weekly_app.command("pack")
def weekly_pack(week: str | None = typer.Option(None, "--week", help="ISO 주 (기본 이번 주)")) -> None:
    """data/weekly/<week>/pack.json + slices/<desk>.json (검증 claim·테마·그래프 diff·전파·시장·캘린더·검토 큐)."""
    from macroweb.db import repo
    from macroweb.synth.pack import write_pack

    repo.init_db()
    conn = repo.connect()
    try:
        paths = write_pack(conn, _week_or_now(week))
    finally:
        conn.close()
    console.print(f"pack: {paths.pack}\nslices: {', '.join(sorted(paths.slices))}")


@weekly_app.command("gate")
def weekly_gate(
    week: str | None = typer.Option(None, "--week"),
    draft: Path | None = typer.Option(
        None, "--draft", help="기본 data/weekly/<week>/draft_final.md|draft.md"
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """결정론 fact-check 게이트: [F]↔claim_id·라벨·수치·금지 표현·격리 라벨·포트폴리오 금액. FAIL 이면 exit 1."""
    from macroweb.db import repo
    from macroweb.synth.gate import check_draft
    from macroweb.synth.run_weekly import find_draft, weekly_dir

    wk = _week_or_now(week)
    path = draft or find_draft(wk)
    if path is None or not path.exists():
        console.print(f"[red]no draft for {wk} (looked in {weekly_dir(wk)})[/]")
        raise typer.Exit(2)
    conn = repo.connect()
    try:
        res = check_draft(conn, path.read_text(encoding="utf-8"))
    finally:
        conn.close()
    if json_out:
        console.print_json(json.dumps(res.as_dict(), ensure_ascii=False))
    else:
        console.print(res.render())
    raise typer.Exit(0 if res.passed else 1)


@weekly_app.command("publish")
def weekly_publish(
    week: str | None = typer.Option(None, "--week"),
    draft: Path | None = typer.Option(None, "--draft"),
    no_notify: bool = typer.Option(False, "--no-notify"),
) -> None:
    """게이트 PASS 인 초안을 reports/<week>.md·drafts/blog-<week>.md·vault/weekly/<week>.md 로 발행 (+알림)."""
    from macroweb.db import repo
    from macroweb.publish.weekly import publish_report
    from macroweb.synth.gate import check_draft
    from macroweb.synth.run_weekly import find_draft

    wk = _week_or_now(week)
    path = draft or find_draft(wk)
    if path is None:
        console.print(f"[red]no draft for {wk}[/]")
        raise typer.Exit(2)
    repo.init_db()
    conn = repo.connect()
    try:
        gate = check_draft(conn, path.read_text(encoding="utf-8"))
        if not gate.passed:
            console.print(gate.render())
            console.print("[red]gate FAIL — not published[/]")
            raise typer.Exit(1)
        res = publish_report(conn, wk, path, notify=not no_notify)
    finally:
        conn.close()
    console.print(
        f"published {res.report} · blog {res.blog} · vault {res.vault_note} · citations {res.citations} · notify {res.notified}"
    )


@weekly_app.command("record")
def weekly_record(
    week: str = typer.Option(..., "--week"),
    step: str = typer.Option(..., "--step"),
    status: str = typer.Option(..., "--status", help="ok|failed"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """스킬 단계 기록 → data/weekly/<week>/steps.jsonl (weekly-report 스킬이 각 단계 끝에 부른다)."""
    from macroweb.synth.run_weekly import record_step

    console.print(str(record_step(week, step, status, note=note)))


@weekly_app.command("run")
def weekly_run(
    week: str | None = typer.Option(None, "--week"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="모델 호출 없이 품질·팩·(초안이 있으면) 게이트까지"
    ),
    timeout: int = typer.Option(7200, "--timeout", help="claude -p 상한 초"),
    skip_quality: bool = typer.Option(False, "--skip-quality"),
) -> None:
    """전체 주간 실행: quality → pack → claude -p '/weekly-report <week>' → gate → publish. 실패해도 부분 산출물 보존."""
    from macroweb.synth.run_weekly import run_weekly

    rep = run_weekly(week, dry_run=dry_run, timeout_s=timeout, skip_quality=skip_quality)
    console.print(rep.render())
    raise typer.Exit(0 if (rep.published or (dry_run and not rep.stopped)) else 1)


@app.command()
def monthly(month: str | None = typer.Option(None, "--month", help="YYYY-MM")) -> None:
    """월간 회고·학습 루프 (Phase 7)."""
    _not_yet("monthly")


if __name__ == "__main__":
    app()
