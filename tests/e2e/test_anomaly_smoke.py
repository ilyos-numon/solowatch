import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUMMARY_RE = re.compile(
    r"SMOKE detected 3/3 injected days, false positive days [01]/11"
)


def run_smoke(db: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "solowatch", "smoke", "--db", str(db), "--out", str(out)],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def smoke(tmp_path_factory: pytest.TempPathFactory) -> dict:
    d = tmp_path_factory.mktemp("smoke")
    proc = run_smoke(d / "a.sqlite", d / "a.json")
    return {"proc": proc, "report": json.loads((d / "a.json").read_text())
            if (d / "a.json").exists() else None}


def test_exit_zero_and_summary_line(smoke: dict) -> None:
    proc = smoke["proc"]
    assert proc.returncode == 0, proc.stderr
    assert SUMMARY_RE.search(proc.stdout), proc.stdout


def test_metrics(smoke: dict) -> None:
    m = smoke["report"]["metrics"]
    assert m["readings"] == 8064
    assert m["hours"] == 672
    assert m["injected_days"] == 3
    assert m["detected_days"] == 3
    assert m["normal_days"] == 11
    assert m["false_positive_days"] <= 1
    assert m["learning_period_anomalies"] == 0


def test_injected_days_detected_in_right_window(smoke: dict) -> None:
    report = smoke["report"]
    assert len(report["injected"]) == 3
    starts = [datetime.fromisoformat(a["window_start"]) for a in report["anomalies"]]
    for inj in report["injected"]:
        day = inj["day"]
        on_day = [s for s in starts if s.date().isoformat() == day]
        assert on_day, f"no anomaly on {day}"
        if inj["kind"] == "no_morning_water":
            assert any(s.hour == 6 for s in on_day)
        elif inj["kind"] == "night_flow":
            assert any(s.hour == 0 for s in on_day)


def test_no_anomaly_in_learning_period(smoke: dict) -> None:
    report = smoke["report"]
    assert report["metrics"]["learning_period_anomalies"] == 0
    cutoff = datetime.fromisoformat("2026-10-19T00:00:00+09:00")
    for a in report["anomalies"]:
        assert datetime.fromisoformat(a["window_start"]) >= cutoff


def test_reproducible(tmp_path: Path) -> None:
    reports = []
    for i in range(2):
        proc = run_smoke(tmp_path / f"r{i}.sqlite", tmp_path / f"r{i}.json")
        assert proc.returncode == 0, proc.stderr
        reports.append(json.loads((tmp_path / f"r{i}.json").read_text()))
    assert reports[0]["anomalies"] == reports[1]["anomalies"]
    assert reports[0]["metrics"] == reports[1]["metrics"]


def test_missing_out_argument_fails(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["uv", "run", "solowatch", "smoke", "--db", str(tmp_path / "x.sqlite")],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
