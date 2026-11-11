"""Simulated water-flow sensor (fixed baseline numbers)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from solowatch.contracts import SLOT, Reading, Scenario, day_type

SLOT_MIN = int(SLOT.total_seconds() // 60)
SLOTS_PER_DAY = 24 * 60 // SLOT_MIN
NIGHT_END_SLOT = 6 * 60 // SLOT_MIN


def _add_event(
    day: np.ndarray, rng: np.random.Generator, center_min: float, liters: float,
    lo_slot: int = 0, hi_slot: int = SLOTS_PER_DAY,
) -> None:
    """Spread `liters` evenly over 1-3 consecutive slots starting near `center_min`."""
    n = int(rng.integers(1, 4))
    start = round(float(center_min) / SLOT_MIN)
    start = max(lo_slot, min(start, hi_slot - n))
    day[start:start + n] += liters / n


def _baseline_day(rng: np.random.Generator, weekend: bool) -> np.ndarray:
    day = np.zeros(SLOTS_PER_DAY, dtype=float)
    # morning: weekday 06:30 ± 20 min, weekend 08:00 ± 30 min, 25 L x lognormal(sigma 0.2)
    m_center, m_spread = (8 * 60, 30) if weekend else (6 * 60 + 30, 20)
    _add_event(day, rng, m_center + rng.uniform(-m_spread, m_spread),
               25.0 * float(rng.lognormal(0.0, 0.2)))
    # lunch 12:30 ± 60 min, 10 L
    _add_event(day, rng, 12 * 60 + 30 + rng.uniform(-60, 60), 10.0)
    # evening 19:00 ± 45 min, 30 L
    _add_event(day, rng, 19 * 60 + rng.uniform(-45, 45), 30.0)
    # night 00-06: Poisson(1) toilet flushes x 6 L, kept inside the night window
    for _ in range(int(rng.poisson(1.0))):
        _add_event(day, rng, rng.uniform(0, 6 * 60), 6.0, 0, NIGHT_END_SLOT)
    return day


def _slot(hour: int, minute: int = 0) -> int:
    return (hour * 60 + minute) // SLOT_MIN


def simulate_water(scenario: Scenario) -> list[Reading]:
    rng = np.random.default_rng(scenario.seed)
    start_dt = scenario.start_dt
    values = np.zeros((scenario.days, SLOTS_PER_DAY), dtype=float)
    for d in range(scenario.days):
        weekend = day_type(start_dt + timedelta(days=d)) == "weekend"
        values[d] = _baseline_day(rng, weekend)

    for anomaly in scenario.anomalies:
        d = (anomaly.day - scenario.start).days
        if not 0 <= d < scenario.days:
            continue
        if anomaly.kind == "no_morning_water":
            values[d, _slot(6):_slot(12)] = 0.0
        elif anomaly.kind == "no_usage_all_day":
            values[d, :] = 0.0
        elif anomaly.kind == "night_flow":
            values[d, _slot(2):_slot(4)] = 5.0
        else:
            raise ValueError(f"unknown anomaly kind: {anomaly.kind}")

    flat = values.reshape(-1)
    return [
        Reading(scenario.sensor_id, start_dt + i * SLOT, float(v))
        for i, v in enumerate(flat)
    ]
