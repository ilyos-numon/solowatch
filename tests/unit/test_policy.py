from __future__ import annotations

from datetime import date, datetime, timedelta

from solowatch.contracts import TZ, Anomaly, HourlyUsage
from solowatch.contracts_mvp import DEFAULT_SENSORS, AwayPeriod
from solowatch.policy import HomePolicy

START = datetime(2026, 10, 5, tzinfo=TZ)  # Monday
LEARN_UNTIL = START + timedelta(days=14)


def _window(sensor_id: str, day: datetime, hour: int, value: float) -> list[HourlyUsage]:
    """One window's first hour carries the whole total; the next hour closes the window."""
    return [HourlyUsage(sensor_id, day.replace(hour=hour), value)]


def _days(start: datetime, count: int) -> list[datetime]:
    return [start + timedelta(days=i) for i in range(count)]


def _policy() -> HomePolicy:
    return HomePolicy(DEFAULT_SENSORS, LEARN_UNTIL)


def _learn_mornings(policy: HomePolicy, liters: float = 25.0) -> None:
    for day in _days(START, 14):
        assert policy.process("water_main", _window("water_main", day, 7, liters)) == []
    assert policy.flush("water_main") is None


def test_one_detector_per_sensor_with_own_floor() -> None:
    policy = _policy()
    for spec in DEFAULT_SENSORS:
        det = policy.detector(spec.sensor_id)
        assert det.min_deviation == spec.min_deviation
        assert det.unit_label == ("L" if spec.unit == "L" else "Ws")
    assert policy.detector("water_main") is not policy.detector("plug_light")


def test_plug_uses_its_own_floor() -> None:
    policy = _policy()
    out: list[Anomaly] = []
    for day in _days(START, 14):
        out += policy.process("plug_light", _window("plug_light", day, 1, 0.0))
    out += policy.process("plug_light", _window("plug_light", LEARN_UNTIL, 1, 720.0))
    flushed = policy.flush("plug_light")
    assert out == []
    assert isinstance(flushed, Anomaly)
    assert flushed.sensor_id == "plug_light"
    assert flushed.actual == 720.0
    assert flushed.reason == "night power 720.0Ws, usual 0.0Ws"
    water = policy.detector("water_main").models()
    assert all(m.gaussian.n_samples == 0 for m in water.values())  # type: ignore[attr-defined]


def test_plug_below_floor_is_silent() -> None:
    policy = _policy()
    for day in _days(START, 14):
        policy.process("plug_light", _window("plug_light", day, 1, 0.0))
    policy.process("plug_light", _window("plug_light", LEARN_UNTIL, 1, 120.0))
    assert policy.flush("plug_light") is None


def test_process_returns_closed_window_anomalies() -> None:
    policy = _policy()
    _learn_mornings(policy)
    day = datetime(2026, 10, 23, tzinfo=TZ)  # Friday
    usage = [HourlyUsage("water_main", day.replace(hour=h), 0.0) for h in range(6, 13)]
    out = policy.process("water_main", usage)
    assert [a.window_start for a in out] == [day.replace(hour=6)]
    assert out[0].expected == 25.0


def test_away_day_is_silent_and_not_learned() -> None:
    policy = _policy()
    _learn_mornings(policy)
    before = policy.learned_mean("water_main", "weekday", "morning")
    assert before == 25.0
    policy.set_away([AwayPeriod(date(2026, 10, 26), date(2026, 10, 27), "외출")])
    out: list[Anomaly] = []
    for day in _days(datetime(2026, 10, 26, tzinfo=TZ), 2):
        out += policy.process(
            "water_main", [HourlyUsage("water_main", day.replace(hour=h), 0.0) for h in range(24)]
        )
    flushed = policy.flush("water_main")
    assert out == [] and flushed is None
    assert policy.learned_mean("water_main", "weekday", "morning") == before
    n = policy.detector("water_main").models()[("weekday", "morning")].gaussian.n_samples  # type: ignore[attr-defined]
    assert n == 10  # weekdays among the 14 learning days


def test_away_is_replaced_by_set_away() -> None:
    policy = _policy()
    _learn_mornings(policy)
    policy.set_away([AwayPeriod(date(2026, 10, 26), date(2026, 10, 27))])
    policy.set_away([])
    day = datetime(2026, 10, 26, tzinfo=TZ)
    policy.process("water_main", _window("water_main", day, 7, 0.0))
    assert isinstance(policy.flush("water_main"), Anomaly)


def _morning_anomaly(policy: HomePolicy) -> Anomaly:
    day = datetime(2026, 10, 23, tzinfo=TZ)
    policy.process("water_main", _window("water_main", day, 7, 0.0))
    anomaly = policy.flush("water_main")
    assert isinstance(anomaly, Anomaly)
    assert anomaly.actual == 0.0 and anomaly.expected == 25.0
    return anomaly


def test_ok_feedback_widens_baseline() -> None:
    policy = _policy()
    _learn_mornings(policy)
    anomaly = _morning_anomaly(policy)
    policy.apply_feedback(anomaly, "ok")
    assert policy.learned_mean("water_main", "weekday", "morning") < 25.0


def test_confirmed_and_checking_feedback_change_nothing() -> None:
    policy = _policy()
    _learn_mornings(policy)
    anomaly = _morning_anomaly(policy)
    policy.apply_feedback(anomaly, "confirmed")
    policy.apply_feedback(anomaly, "checking")
    assert policy.learned_mean("water_main", "weekday", "morning") == 25.0
    n = policy.detector("water_main").models()[("weekday", "morning")].gaussian.n_samples  # type: ignore[attr-defined]
    assert n == 10  # weekdays among the 14 learning days
