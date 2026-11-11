from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest

from solowatch.contracts import DEFAULT_SCENARIO, TZ, Reading
from solowatch.simulate import simulate_water


@pytest.fixture(scope="module")
def readings() -> list[Reading]:
    return simulate_water(DEFAULT_SCENARIO)


def _sum(readings: list[Reading], day: date, h_lo: int, h_hi: int) -> float:
    return sum(
        r.value for r in readings if r.ts.date() == day and h_lo <= r.ts.hour < h_hi
    )


def _baseline_days() -> list[date]:
    injected = {a.day for a in DEFAULT_SCENARIO.anomalies}
    days = [
        (DEFAULT_SCENARIO.start_dt.date().toordinal() + i)
        for i in range(DEFAULT_SCENARIO.days)
    ]
    return [date.fromordinal(d) for d in days if date.fromordinal(d) not in injected]


def test_default_scenario_length(readings: list[Reading]) -> None:
    assert len(readings) == 8064
    assert readings[0].ts == datetime(2026, 10, 5, 0, 0, tzinfo=TZ)
    assert readings[0].ts.isoformat() == "2026-10-05T00:00:00+09:00"
    assert readings[-1].ts.isoformat() == "2026-11-01T23:55:00+09:00"
    assert all(r.sensor_id == "water_main" for r in readings)
    assert all(r.ts.tzinfo is not None for r in readings)
    assert all(r.value >= 0 for r in readings)


def test_morning_usage_present_on_baseline_days(readings: list[Reading]) -> None:
    for day in _baseline_days():
        assert _sum(readings, day, 6, 12) >= 10.0, day


def test_night_usage_small_on_baseline_days(readings: list[Reading]) -> None:
    for day in _baseline_days():
        assert _sum(readings, day, 0, 6) <= 30.0, day


def test_same_seed_same_output(readings: list[Reading]) -> None:
    again = simulate_water(DEFAULT_SCENARIO)
    assert len(again) == len(readings)
    assert all(a == b for a, b in zip(again, readings, strict=True))


def test_different_seed_different_output(readings: list[Reading]) -> None:
    other = simulate_water(replace(DEFAULT_SCENARIO, seed=43))
    assert other != readings


def test_no_morning_water(readings: list[Reading]) -> None:
    day = date(2026, 10, 23)
    assert _sum(readings, day, 6, 12) == 0
    assert _sum(readings, day, 18, 24) > 0


def test_no_usage_all_day(readings: list[Reading]) -> None:
    assert _sum(readings, date(2026, 10, 28), 0, 24) == 0


def test_night_flow(readings: list[Reading]) -> None:
    assert _sum(readings, date(2026, 10, 31), 2, 4) == 120.0


def test_default_scenario_anomaly_days() -> None:
    assert [a.day for a in DEFAULT_SCENARIO.anomalies] == [
        date(2026, 10, 23), date(2026, 10, 28), date(2026, 10, 31),
    ]
