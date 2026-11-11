from __future__ import annotations

from datetime import datetime, timedelta

from river.anomaly import GaussianScorer

from solowatch.contracts import (
    DEFAULT_THRESHOLD,
    GRACE_PERIOD,
    WINDOWS,
    Anomaly,
    DayType,
    Detector,
    HourlyUsage,
    WindowName,
    day_type,
    window_of,
    window_start,
)

_DAY_TYPES: tuple[DayType, ...] = ("weekday", "weekend")
# Totals within this many liters of the learned mean are normal even when river's sigma is ~0
# (identical training totals); 5 L is below one toilet flush, so no real event hides under it.
MIN_DEVIATION_L = 5.0


class WindowDetector(Detector):
    """Folds hourly usage into (day_type, window) totals scored by river's GaussianScorer."""

    def __init__(
        self,
        learn_until: datetime,
        threshold: float = DEFAULT_THRESHOLD,
        grace_period: int = GRACE_PERIOD,
        min_deviation: float = MIN_DEVIATION_L,
        unit_label: str = "L",
    ) -> None:
        self.learn_until = learn_until
        self.threshold = threshold
        self.min_deviation = min_deviation
        self.unit_label = unit_label
        self._measure = "power" if unit_label == "Ws" else "usage"
        self._models: dict[tuple[DayType, WindowName], GaussianScorer] = {
            (dt, w): GaussianScorer(grace_period=grace_period)
            for dt in _DAY_TYPES
            for w in WINDOWS
        }
        self._sensor_id: str | None = None
        self._start: datetime | None = None
        self._total = 0.0

    def models(self) -> dict[tuple[DayType, WindowName], object]:
        return dict(self._models)

    def update(self, usage: HourlyUsage) -> Anomaly | None:
        start = window_start(usage.hour_start)
        result: Anomaly | None = None
        if self._start is not None and (start != self._start or usage.sensor_id != self._sensor_id):
            result = self._close()
        if self._start is None:
            self._sensor_id = usage.sensor_id
            self._start = start
            self._total = 0.0
        self._total += usage.value
        return result

    def flush(self) -> Anomaly | None:
        if self._start is None:
            return None
        return self._close()

    def _close(self) -> Anomaly | None:
        assert self._start is not None and self._sensor_id is not None
        start, sensor_id, actual = self._start, self._sensor_id, self._total
        self._start = None
        self._sensor_id = None
        self._total = 0.0

        name = window_of(start)
        lo, hi = WINDOWS[name]
        scorer = self._models[(day_type(start), name)]
        score = float(scorer.score_one(None, actual))
        expected = float(scorer.gaussian.mu)  # river proba.Gaussian learned mean

        if start < self.learn_until:
            scorer.learn_one(None, actual)
            return None
        if score >= self.threshold and abs(actual - expected) >= self.min_deviation:
            return Anomaly(
                sensor_id=sensor_id,
                window_start=start,
                window_end=start + timedelta(hours=hi - lo),
                score=score,
                expected=expected,
                actual=actual,
                reason=(
                    f"{name} {self._measure} {actual:.1f}{self.unit_label},"
                    f" usual {expected:.1f}{self.unit_label}"
                ),
            )
        scorer.learn_one(None, actual)
        return None
