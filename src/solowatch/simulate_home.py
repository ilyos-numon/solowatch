"""Simulated MVP household: water main + three smart plugs (home-simulation spec)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from solowatch.contracts import SLOT, Reading, day_type
from solowatch.contracts_mvp import HomeScenario
from solowatch.simulate import SLOT_MIN, SLOTS_PER_DAY, simulate_water

FRIDGE_W = 90.0
FRIDGE_ON, FRIDGE_PERIOD = 2, 5
TV_STANDBY_W = 2.0
TV_ON_W = 80.0
LIGHT_W = 10.0
PLUG_IDS = ("plug_fridge", "plug_tv", "plug_light")


def _slot(hour: int, minute: int = 0) -> int:
    return (hour * 60 + minute) // SLOT_MIN


def _clip(slot: float) -> int:
    return max(0, min(SLOTS_PER_DAY, round(slot)))


def _fridge_day(rng: np.random.Generator) -> np.ndarray:
    phase = int(rng.integers(0, FRIDGE_PERIOD))
    idx = np.arange(SLOTS_PER_DAY)
    return np.where((idx + phase) % FRIDGE_PERIOD < FRIDGE_ON, FRIDGE_W, 0.0)


def _tv_day(rng: np.random.Generator, weekend: bool) -> np.ndarray:
    day = np.full(SLOTS_PER_DAY, TV_STANDBY_W)
    start_min = 19 * 60 + rng.uniform(-30, 30)
    dur_min = 3.5 * 60 + rng.uniform(-30, 30)
    day[_clip(start_min / SLOT_MIN):_clip((start_min + dur_min) / SLOT_MIN)] = TV_ON_W
    if weekend:
        day[_slot(14):_slot(16)] = TV_ON_W
    return day


def _light_day(rng: np.random.Generator, weekend: bool) -> np.ndarray:
    day = np.zeros(SLOTS_PER_DAY)
    on_min = 18 * 60 + rng.uniform(-30, 30)
    off_min = 23 * 60 + rng.uniform(-30, 30)
    day[_clip(on_min / SLOT_MIN):_clip(off_min / SLOT_MIN)] = LIGHT_W
    if not weekend:
        day[_slot(6):_slot(7, 30)] = LIGHT_W
    return day


def simulate_home(scenario: HomeScenario) -> dict[str, list[Reading]]:
    water = simulate_water(scenario.water_scenario())
    rng = np.random.default_rng(scenario.seed + 1)
    start_dt = scenario.start_dt
    plugs = {pid: np.zeros((scenario.days, SLOTS_PER_DAY)) for pid in PLUG_IDS}
    for d in range(scenario.days):
        weekend = day_type(start_dt + timedelta(days=d)) == "weekend"
        plugs["plug_fridge"][d] = _fridge_day(rng)
        plugs["plug_tv"][d] = _tv_day(rng, weekend)
        plugs["plug_light"][d] = _light_day(rng, weekend)

    for event in scenario.events:
        d = (event.day - scenario.start).days
        if not 0 <= d < scenario.days:
            continue
        if event.kind in ("light_all_night", "different_morning"):
            plugs["plug_light"][d, :_slot(6)] = LIGHT_W
        elif event.kind == "no_tv_evening":
            plugs["plug_tv"][d, _slot(18):] = TV_STANDBY_W
        elif event.kind == "fridge_off":
            plugs["plug_fridge"][d, :] = 0.0
        # water kinds (and the water half of different_morning) come from simulate_water

    water_values = np.array([r.value for r in water]).reshape(scenario.days, SLOTS_PER_DAY)
    for away_start, away_end in scenario.away:
        lo = max(0, (away_start - scenario.start).days)
        hi = min(scenario.days, (away_end - scenario.start).days + 1)
        if lo >= hi:
            continue
        water_values[lo:hi] = 0.0
        plugs["plug_tv"][lo:hi] = 0.0
        plugs["plug_light"][lo:hi] = 0.0

    out: dict[str, list[Reading]] = {
        "water_main": [
            r if r.value == v else Reading(r.sensor_id, r.ts, float(v))
            for r, v in zip(water, water_values.reshape(-1), strict=True)
        ],
    }
    for pid in PLUG_IDS:
        out[pid] = [
            Reading(pid, start_dt + i * SLOT, float(v))
            for i, v in enumerate(plugs[pid].reshape(-1))
        ]
    return out
