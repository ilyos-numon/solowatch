"""Rhythm figure: share of days each sensor was active per hour (portfolio-docs spec).

Drawing is matplotlib (imshow); this module only turns the store into a 4x24 matrix.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from solowatch.contracts import TZ
from solowatch.contracts_mvp import DEFAULT_HOME, DEFAULT_SENSORS, InjectedEvent, SensorSpec
from solowatch.store import SqliteStore

SCENARIOS = {"default": DEFAULT_HOME}
SENSOR_LABEL_EN = {"water_main": "water", "plug_fridge": "fridge", "plug_tv": "tv", "plug_light": "light"}
EVENT_LABEL_EN = {
    "no_morning_water": "no morning water", "no_usage_all_day": "no water all day",
    "night_flow": "water at night", "light_all_night": "light on all night",
    "no_tv_evening": "no TV in evening", "fridge_off": "fridge off",
    "different_morning": "different morning",
}


def _reading_span(store: SqliteStore) -> tuple[date, date] | None:
    row = store._con.execute("SELECT MIN(ts), MAX(ts) FROM readings").fetchone()
    if row is None or row[0] is None:
        return None
    first = datetime.fromisoformat(row[0]).astimezone(TZ).date()
    last = datetime.fromisoformat(row[1]).astimezone(TZ).date()
    return first, last


def _activity(store: SqliteStore, sensors: list[SensorSpec], start: date, days: int) -> list[list[float]]:
    lo = datetime.combine(start, datetime.min.time(), TZ)
    hi = lo + timedelta(days=days)
    rows: list[list[float]] = []
    for spec in sensors:
        active = [0] * 24
        for h in store.hourly_usage(spec.sensor_id, lo, hi):
            if h.value >= spec.active_threshold:
                active[h.hour_start.astimezone(TZ).hour] += 1
        rows.append([n / days for n in active])
    return rows


def render(store: SqliteStore, sensors: Iterable[SensorSpec], out: str, days: int = 28,
           events: Iterable[InjectedEvent] = ()) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    specs = list(sensors)
    span = _reading_span(store)
    if span is None:
        raise ValueError("store has no readings")
    end = span[1]
    start = max(span[0], end - timedelta(days=days - 1))
    n_days = (end - start).days + 1
    matrix = _activity(store, specs, start, n_days)
    labels = [SENSOR_LABEL_EN.get(s.sensor_id, s.sensor_id) for s in specs]

    fig, (ax, tl) = plt.subplots(2, 1, figsize=(14, 7.5), dpi=120,
                                 gridspec_kw={"height_ratios": [3, 1.6]})
    im = ax.imshow(matrix, aspect="auto", cmap="Blues", vmin=0.0, vmax=1.0)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xticks(range(24), [f"{h:02d}" for h in range(24)])
    ax.set_xlabel("hour of day")
    ax.set_title(f"SoloWatch daily rhythm - share of days active per hour "
                 f"({start.isoformat()} .. {end.isoformat()}, {n_days} days, simulated)")
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            if v >= 0.05:
                ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=7,
                        color="white" if v > 0.6 else "#1f3b57")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01, label="share of days")

    ev = [e for e in events if start <= e.day <= end]
    tl.set_xlim(-0.5, n_days - 0.5)
    tl.set_ylim(-0.5, max(1, len(ev)) - 0.5)
    tl.set_xticks(range(n_days), [(start + timedelta(days=d)).strftime("%m-%d") for d in range(n_days)],
                  rotation=60, fontsize=7)
    tl.set_yticks([])
    tl.grid(axis="x", color="#dddddd", linewidth=0.5)
    tl.set_title("injected event days (what the detector should notice)", fontsize=9, loc="left")
    for k, e in enumerate(sorted(ev, key=lambda e: e.day)):
        x = (e.day - start).days
        tl.plot([x], [k], marker="v", color="#c0392b", markersize=8)
        tl.annotate(EVENT_LABEL_EN.get(e.kind, e.kind), (x, k), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=8)
    if not ev:
        tl.text(n_days / 2, 0, "no events given", ha="center", va="center", color="#888888")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="render-rhythm", description=__doc__)
    ap.add_argument("--db", required=True, help="SQLite store with readings")
    ap.add_argument("--out", required=True, help="output PNG path")
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--scenario", default=None, choices=sorted(SCENARIOS),
                    help="mark this simulated scenario's injected event days")
    args = ap.parse_args(argv)
    scenario = SCENARIOS[args.scenario] if args.scenario else None
    store = SqliteStore(args.db)
    try:
        sensors = scenario.sensors if scenario else DEFAULT_SENSORS
        render(store, sensors, args.out, days=args.days, events=scenario.events if scenario else ())
    except ValueError as e:
        print(f"render-rhythm: {e}", file=sys.stderr)
        return 2
    finally:
        store.close()
    print(f"RHYTHM {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
