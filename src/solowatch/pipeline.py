"""`solowatch smoke`: simulate -> store -> detect -> JSON report + one summary line."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from solowatch.contracts import DEFAULT_SCENARIO, TZ, Anomaly, Scenario
from solowatch.detect import WindowDetector
from solowatch.simulate import simulate_water
from solowatch.store import SqliteStore


def _anomaly_dict(a: Anomaly) -> dict[str, Any]:
    return {
        "sensor_id": a.sensor_id,
        "window_start": a.window_start.astimezone(TZ).isoformat(),
        "window_end": a.window_end.astimezone(TZ).isoformat(),
        "score": a.score,
        "expected": a.expected,
        "actual": a.actual,
        "reason": a.reason,
    }


def _metrics(scenario: Scenario, readings: int, hours: int,
             anomalies: list[Anomaly]) -> dict[str, int]:
    injected = {a.day for a in scenario.anomalies}
    learn_until = scenario.learn_until
    flagged = {a.window_start.astimezone(TZ).date() for a in anomalies}
    monitor_days = {
        scenario.start + timedelta(days=d) for d in range(scenario.learn_days, scenario.days)
    }
    normal: set[date] = monitor_days - injected
    return {
        "readings": readings,
        "hours": hours,
        "injected_days": len(injected),
        "detected_days": len(injected & flagged),
        "normal_days": len(normal),
        "false_positive_days": len(normal & flagged),
        "learning_period_anomalies": sum(1 for a in anomalies if a.window_start < learn_until),
    }


def run_smoke(scenario: Scenario, db_path: str, out_path: str) -> dict:
    db = Path(db_path)
    out = Path(out_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()

    store = SqliteStore(str(db))
    try:
        store.insert_readings(simulate_water(scenario))
        readings = store.count_readings(scenario.sensor_id)
        usage = store.hourly_usage(scenario.sensor_id, scenario.start_dt, scenario.end_dt)

        detector = WindowDetector(learn_until=scenario.learn_until)
        found: list[Anomaly] = []
        for u in usage:
            a = detector.update(u)
            if a is not None:
                found.append(a)
        last = detector.flush()
        if last is not None:
            found.append(last)
        store.insert_anomalies(found)
        anomalies = store.list_anomalies(scenario.sensor_id)
    finally:
        store.close()

    report: dict[str, Any] = {
        "scenario": {
            "sensor_id": scenario.sensor_id,
            "start": scenario.start.isoformat(),
            "days": scenario.days,
            "seed": scenario.seed,
            "learn_days": scenario.learn_days,
        },
        "injected": [{"kind": a.kind, "day": a.day.isoformat()} for a in scenario.anomalies],
        "anomalies": [_anomaly_dict(a) for a in anomalies],
        "metrics": _metrics(scenario, readings, len(usage), anomalies),
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solowatch")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="simulate -> store -> detect, write a JSON report")
    smoke.add_argument("--db", required=True, help="SQLite path (recreated)")
    smoke.add_argument("--out", required=True, help="JSON report path")
    smoke.add_argument("--seed", type=int, default=None, help="override scenario seed")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    try:
        scenario = DEFAULT_SCENARIO
        if args.seed is not None:
            scenario = dataclasses.replace(scenario, seed=args.seed)
        m = run_smoke(scenario, args.db, args.out)["metrics"]
    except (OSError, ValueError, sqlite3.Error) as e:  # other errors propagate -> exit 1
        print(f"solowatch smoke failed: {e}", file=sys.stderr)
        return 1
    print(
        f"SMOKE detected {m['detected_days']}/{m['injected_days']} injected days, "
        f"false positive days {m['false_positive_days']}/{m['normal_days']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
