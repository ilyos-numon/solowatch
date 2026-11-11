from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from solowatch import cli
from solowatch.store import SqliteStore

COMMANDS = ("smoke", "simulate-home", "publish-mock", "daemon", "ops-report", "render-rhythm",
            "demo-server")


def test_help_lists_seven_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for name in COMMANDS:
        assert name in out


def test_no_command_exits_2() -> None:
    assert cli.main([]) == 2
    assert cli.main(["bogus"]) == 2


def test_smoke_delegates_to_pipeline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["smoke", "--db", str(tmp_path / "s.sqlite"), "--out", str(tmp_path / "r.json")])
    assert code == 0
    assert "SMOKE detected 3/3 injected days, false positive days 0/11" in capsys.readouterr().out


def test_simulate_home_writes_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "h.sqlite"
    assert cli.main(["simulate-home", "--db", str(db), "--limit-days", "1"]) == 0
    store = SqliteStore(str(db))
    try:
        assert store.count_readings() == 4 * 288
        assert store.sensor_ids() == ["plug_fridge", "plug_light", "plug_tv", "water_main"]
    finally:
        store.close()
    assert "SIMULATED 1152 readings for 4 sensors" in capsys.readouterr().out


@pytest.mark.parametrize(("command", "module"), [
    ("ops-report", "solowatch.ops_report"),
    ("render-rhythm", "solowatch.render_rhythm"),
    ("daemon", "solowatch.daemon"),
    ("publish-mock", "solowatch.mock_publisher"),
    ("demo-server", "solowatch.demo_server"),
])
def test_passes_argv_through_unchanged(command: str, module: str,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    fake = types.ModuleType(module)
    fake.main = lambda argv=None: seen.append(list(argv or [])) or 7  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module, fake)
    argv = ["--db", "x.sqlite", "--out", "y", "--scenario", "default", "--help"]
    assert cli.main([command, *argv]) == 7
    assert seen == [argv]


def test_missing_module_reports_and_exits_2(monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(cli.COMMANDS, "ops-report",
                        ("solowatch.not_there_yet", cli.COMMANDS["ops-report"][1]))
    assert cli.main(["ops-report", "--db", "x"]) == 2
    assert "solowatch.not_there_yet" in capsys.readouterr().err
