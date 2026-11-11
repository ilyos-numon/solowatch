from __future__ import annotations

from datetime import datetime, timedelta

from river.anomaly import GaussianScorer

from solowatch.contracts import TZ, Anomaly, HourlyUsage, day_type, window_of
from solowatch.detect import WindowDetector

SENSOR = "water_main"
START = datetime(2026, 10, 5, tzinfo=TZ)  # Monday
LEARN_UNTIL = START + timedelta(days=14)
MORNING_VALUES = (22.0, 25.0, 28.0)  # 25 +/- 3 L


def _morning(day: datetime, liters: float) -> HourlyUsage:
    return HourlyUsage(SENSOR, day.replace(hour=7), liters)


def _trained() -> WindowDetector:
    det = WindowDetector(learn_until=LEARN_UNTIL)
    for i in range(14):
        assert det.update(_morning(START + timedelta(days=i), MORNING_VALUES[i % 3])) is None
    return det


def _weekday_after_learning() -> datetime:
    day = LEARN_UNTIL
    while day_type(day) != "weekday":
        day += timedelta(days=1)
    return day


def test_friday_7am_is_weekday_morning() -> None:
    ts = datetime(2026, 10, 23, 7, tzinfo=TZ)
    assert (day_type(ts), window_of(ts)) == ("weekday", "morning")
    det = WindowDetector(learn_until=START)
    det.update(HourlyUsage(SENSOR, ts, 5.0))
    det.flush()
    models = det.models()
    assert models[("weekday", "morning")].gaussian.n_samples == 1  # type: ignore[attr-defined]
    others = [m for k, m in models.items() if k != ("weekday", "morning")]
    assert all(m.gaussian.n_samples == 0 for m in others)  # type: ignore[attr-defined]


def test_models_are_eight_gaussian_scorers() -> None:
    models = WindowDetector(learn_until=LEARN_UNTIL).models()
    assert len(models) == 8
    assert all(isinstance(m, GaussianScorer) for m in models.values())


def test_learning_period_is_silent() -> None:
    det = _trained()
    # Last learning-day window closed with an extreme value: still silent, still learned.
    det.update(_morning(LEARN_UNTIL - timedelta(days=1), 0.0))
    assert det.update(_morning(LEARN_UNTIL - timedelta(days=1) + timedelta(hours=1), 0.0)) is None
    assert det.flush() is None


def test_no_morning_water_is_anomaly() -> None:
    det = _trained()
    day = _weekday_after_learning()
    assert det.update(_morning(day, 0.0)) is None  # closes the last learning window
    anomaly = det.flush()
    assert isinstance(anomaly, Anomaly)
    assert anomaly.window_start == day.replace(hour=6)
    assert anomaly.window_end == day.replace(hour=12)
    assert anomaly.actual == 0.0
    assert anomaly.score >= 0.995
    assert 22.0 <= anomaly.expected <= 28.0
    assert anomaly.reason == f"morning usage 0.0L, usual {anomaly.expected:.1f}L"


def test_normal_morning_is_not_anomaly() -> None:
    det = _trained()
    det.update(_morning(_weekday_after_learning(), 24.0))
    assert det.flush() is None


def test_anomalous_window_is_not_learned() -> None:
    det = _trained()
    day = _weekday_after_learning()
    det.update(_morning(day, 0.0))
    first = det.flush()
    det.update(_morning(day + timedelta(days=1), 0.0))
    second = det.flush()
    assert first is not None and second is not None
    assert second.expected == first.expected


def test_constant_history_does_not_flag_same_value() -> None:
    # Identical training values give river's Gaussian sigma 0; the usual value must stay normal.
    det = WindowDetector(learn_until=LEARN_UNTIL)
    for i in range(14):
        assert det.update(_morning(START + timedelta(days=i), 30.0)) is None
    day = _weekday_after_learning()
    det.update(_morning(day, 30.0))
    assert det.flush() is None
    det.update(_morning(day + timedelta(days=1), 0.0))
    anomaly = det.flush()
    assert isinstance(anomaly, Anomaly)
    assert anomaly.actual == 0.0
    assert anomaly.expected == 30.0


def _weekday_nights(start: datetime, count: int) -> list[datetime]:
    days: list[datetime] = []
    day = start
    while len(days) < count:
        if day_type(day) == "weekday":
            days.append(day)
        day += timedelta(days=1)
    return days


def test_plug_floor_uses_min_deviation() -> None:
    nights = _weekday_nights(START, 16)
    learn_until = nights[14]
    det = WindowDetector(learn_until=learn_until, min_deviation=300.0, unit_label="Ws")
    for day in nights[:14]:
        assert det.update(HourlyUsage("plug_light", day.replace(hour=1), 0.0)) is None
    assert det.update(HourlyUsage("plug_light", nights[14].replace(hour=1), 120.0)) is None
    assert det.flush() is None
    det.update(HourlyUsage("plug_light", nights[15].replace(hour=1), 720.0))
    anomaly = det.flush()
    assert isinstance(anomaly, Anomaly)
    assert anomaly.actual == 720.0
    assert anomaly.reason == f"night power 720.0Ws, usual {anomaly.expected:.1f}Ws"


def test_default_min_deviation_is_liters() -> None:
    from solowatch.detect import MIN_DEVIATION_L

    det = WindowDetector(learn_until=LEARN_UNTIL)
    assert det.min_deviation == MIN_DEVIATION_L == 5.0
    assert det.unit_label == "L"
