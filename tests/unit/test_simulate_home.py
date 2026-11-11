from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from solowatch.contracts import Reading
from solowatch.contracts_mvp import DEFAULT_HOME, DEFAULT_SENSORS
from solowatch.simulate import simulate_water
from solowatch.simulate_home import simulate_home

SENSOR_IDS = ["water_main", "plug_fridge", "plug_tv", "plug_light"]


@pytest.fixture(scope="module")
def home() -> dict[str, list[Reading]]:
    return simulate_home(DEFAULT_HOME)


def _sum(readings: list[Reading], day: date, h_lo: int, h_hi: int) -> float:
    return sum(r.value for r in readings if r.ts.date() == day and h_lo <= r.ts.hour < h_hi)


def _baseline_days() -> list[date]:
    skip = {e.day for e in DEFAULT_HOME.events}
    for s, e in DEFAULT_HOME.away:
        skip |= {s + timedelta(days=i) for i in range((e - s).days + 1)}
    days = [DEFAULT_HOME.start + timedelta(days=i) for i in range(DEFAULT_HOME.days)]
    return [d for d in days if d not in skip]


def test_default_sensor_ids() -> None:
    assert [s.sensor_id for s in DEFAULT_SENSORS] == SENSOR_IDS


def test_default_home_length_and_water_equals_simulate_water(
    home: dict[str, list[Reading]],
) -> None:
    assert list(home) == SENSOR_IDS
    assert [len(v) for v in home.values()] == [8064] * 4
    water = simulate_water(DEFAULT_HOME.water_scenario())
    away = DEFAULT_HOME.away_periods()
    outside = [r for r in water if not any(p.covers(r.ts) for p in away)]
    got = [r for r in home["water_main"] if not any(p.covers(r.ts) for p in away)]
    assert got == outside
    no_away = replace(DEFAULT_HOME, away=())
    assert simulate_home(no_away)["water_main"] == water


def test_light_off_at_night_on_baseline_days(home: dict[str, list[Reading]]) -> None:
    for day in _baseline_days():
        assert _sum(home["plug_light"], day, 0, 6) == 0


def test_tv_evening_on_baseline_days(home: dict[str, list[Reading]]) -> None:
    for day in _baseline_days():
        assert _sum(home["plug_tv"], day, 18, 24) >= 2000


def test_fridge_every_hour_on_baseline_days(home: dict[str, list[Reading]]) -> None:
    for day in _baseline_days():
        for h in range(24):
            assert _sum(home["plug_fridge"], day, h, h + 1) > 0


def test_different_morning(home: dict[str, list[Reading]]) -> None:
    day = date(2026, 10, 30)
    assert _sum(home["water_main"], day, 6, 12) == 0
    assert _sum(home["plug_light"], day, 0, 6) == pytest.approx(720)


def test_plug_events(home: dict[str, list[Reading]]) -> None:
    assert _sum(home["plug_light"], date(2026, 10, 21), 0, 6) == pytest.approx(720)
    assert _sum(home["plug_tv"], date(2026, 10, 25), 18, 24) == pytest.approx(2 * 72)
    assert _sum(home["plug_fridge"], date(2026, 10, 29), 0, 24) == 0


def test_away_days_are_silent(home: dict[str, list[Reading]]) -> None:
    for day in (date(2026, 10, 26), date(2026, 10, 27)):
        for sid in ("water_main", "plug_tv", "plug_light"):
            assert _sum(home[sid], day, 0, 24) == 0
        assert _sum(home["plug_fridge"], day, 0, 24) > 0


def test_default_events() -> None:
    events = DEFAULT_HOME.events
    assert len(events) == 7
    assert len({e.kind for e in events}) == 7
    for e in events:
        assert date(2026, 10, 19) <= e.day <= date(2026, 11, 1)
        assert e.day not in (date(2026, 10, 26), date(2026, 10, 27))


def test_determinism(home: dict[str, list[Reading]]) -> None:
    assert simulate_home(DEFAULT_HOME) == home
    other = simulate_home(replace(DEFAULT_HOME, seed=7))
    assert other != home
    assert other["plug_tv"] != home["plug_tv"]
