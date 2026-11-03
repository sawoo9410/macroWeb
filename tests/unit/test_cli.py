import json

from typer.testing import CliRunner

from macroweb.cli import app

runner = CliRunner()


def test_version() -> None:
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0 and "macroweb" in r.stdout


def test_config_validate_ok() -> None:
    r = runner.invoke(app, ["config", "validate"])
    assert r.exit_code == 0, r.stdout


def test_db_init_then_doctor_quick_json_has_no_fail() -> None:
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    r = runner.invoke(app, ["doctor", "--quick", "--json"])
    data = json.loads(r.stdout)
    fails = [c for c in data["checks"] if c["status"] == "FAIL"]
    assert not fails, fails
    assert r.exit_code == 0


def test_phase_show_and_stage_stubs() -> None:
    assert runner.invoke(app, ["phase", "show"]).exit_code == 0
    r = runner.invoke(app, ["monthly"])  # still a Phase 7 stub; everything up to weekly is real now
    assert r.exit_code == 3
    assert runner.invoke(app, ["source", "list"]).exit_code == 0
    assert runner.invoke(app, ["cost"]).exit_code == 0
