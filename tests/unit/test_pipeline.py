from __future__ import annotations

import json
from pathlib import Path

import pytest

from solowatch.contracts import DEFAULT_SCENARIO
from solowatch.pipeline import main, run_smoke

METRIC_KEYS = {
    "readings", "hours", "injected_days", "detected_days", "normal_days",
    "false_positive_days", "learning_period_anomalies",
}


def test_run_smoke_report_shape(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "sw.sqlite"
    out = tmp_path / "out" / "report.json"
    report = run_smoke(DEFAULT_SCENARIO, str(db), str(out))
    assert set(report) == {"scenario", "injected", "anomalies", "metrics"}
    assert set(report["metrics"]) == METRIC_KEYS
    assert all(isinstance(v, int) for v in report["metrics"].values())
    assert report["scenario"] == {
        "sensor_id": "water_main", "start": "2026-10-05", "days": 28, "seed": 42,
        "learn_days": 14,
    }
    assert report["injected"][0] == {"kind": "no_morning_water", "day": "2026-10-23"}
    for a in report["anomalies"]:
        assert set(a) == {"sensor_id", "window_start", "window_end", "score", "expected",
                          "actual", "reason"}
        assert a["window_start"].endswith("+09:00")
    assert json.loads(out.read_text()) == report
    assert db.exists()


def test_run_smoke_replaces_existing_db(tmp_path: Path) -> None:
    db = tmp_path / "sw.sqlite"
    first = run_smoke(DEFAULT_SCENARIO, str(db), str(tmp_path / "a.json"))
    second = run_smoke(DEFAULT_SCENARIO, str(db), str(tmp_path / "b.json"))
    assert first["metrics"] == second["metrics"]
    assert first["anomalies"] == second["anomalies"]


def test_main_prints_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "r.json"
    code = main(["smoke", "--db", str(tmp_path / "x.sqlite"), "--out", str(out), "--seed", "42"])
    assert code == 0
    m = json.loads(out.read_text())["metrics"]
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line == (
        f"SMOKE detected {m['detected_days']}/{m['injected_days']} injected days, "
        f"false positive days {m['false_positive_days']}/{m['normal_days']}"
    )


@pytest.mark.parametrize("argv", [[], ["smoke"], ["smoke", "--db", "x.sqlite"], ["bogus"],
                                  ["smoke", "--db", "a", "--out", "b", "--seed", "x"]])
def test_main_bad_args_nonzero(argv: list[str]) -> None:
    try:
        code = main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    assert code != 0
