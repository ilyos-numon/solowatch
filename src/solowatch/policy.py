from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from river.anomaly import GaussianScorer

from solowatch.contracts import (
    DEFAULT_THRESHOLD,
    TZ,
    WINDOWS,
    Anomaly,
    DayType,
    HourlyUsage,
    WindowName,
    day_type,
    window_of,
    window_start,
)
from solowatch.contracts_mvp import AwayPeriod, SensorSpec, Verdict
from solowatch.detect import WindowDetector

_UNIT_LABEL = {"L": "L", "W": "Ws"}  # plug window totals are watt-slots


class HomePolicy:
    """One river-backed WindowDetector per sensor plus away suppression and feedback learning.

    This layer only decides which windows reach the scorer; the scoring math stays in river.
    """

    def __init__(
        self,
        sensors: Iterable[SensorSpec],
        learn_until: datetime,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self._detectors: dict[str, WindowDetector] = {
            s.sensor_id: WindowDetector(
                learn_until,
                threshold,
                min_deviation=s.min_deviation,
                unit_label=_UNIT_LABEL[s.unit],
            )
            for s in sensors
        }
        self._away: tuple[AwayPeriod, ...] = ()

    def set_away(self, periods: Iterable[AwayPeriod]) -> None:
        self._away = tuple(periods)

    def detector(self, sensor_id: str) -> WindowDetector:
        return self._detectors[sensor_id]

    def process(self, sensor_id: str, usage: Iterable[HourlyUsage]) -> list[Anomaly]:
        det = self._detectors[sensor_id]
        out: list[Anomaly] = []
        for u in usage:
            if self._is_away(u.hour_start):
                continue  # neither scored nor learned
            anomaly = det.update(u)
            if anomaly is not None:
                out.append(anomaly)
        return out

    def flush(self, sensor_id: str) -> Anomaly | None:
        return self._detectors[sensor_id].flush()

    def apply_feedback(self, anomaly: Anomaly, verdict: Verdict) -> None:
        if verdict != "ok":
            return
        self._scorer(anomaly.sensor_id, day_type(anomaly.window_start),
                     window_of(anomaly.window_start)).learn_one(None, anomaly.actual)

    def _learned_mu(self, sensor_id: str, day_type: DayType, window: WindowName) -> float:
        return float(self._scorer(sensor_id, day_type, window).gaussian.mu)

    learned_mean = _learned_mu

    def _scorer(self, sensor_id: str, dtype: DayType, window: WindowName) -> GaussianScorer:
        scorer = self._detectors[sensor_id].models()[(dtype, window)]
        assert isinstance(scorer, GaussianScorer)
        return scorer

    def _is_away(self, hour: datetime) -> bool:
        ws = window_start(hour.astimezone(TZ))
        lo, hi = WINDOWS[window_of(ws)]
        we = ws + timedelta(hours=hi - lo)
        for p in self._away:
            away_start = datetime.combine(p.start_date, datetime.min.time(), TZ)
            away_end = datetime.combine(p.end_date, datetime.min.time(), TZ) + timedelta(days=1)
            if ws < away_end and away_start < we:
                return True
        return False
