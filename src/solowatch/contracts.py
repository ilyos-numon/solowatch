# src/solowatch/contracts.py  — 동결 파일. 변경 = BLOCKED.
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Seoul")
SLOT = timedelta(minutes=5)                       # 모의 센서 샘플 간격
WindowName = Literal["night", "morning", "afternoon", "evening"]
WINDOWS: dict[WindowName, tuple[int, int]] = {    # 시작시, 끝시(배타)
    "night": (0, 6), "morning": (6, 12), "afternoon": (12, 18), "evening": (18, 24),
}
DayType = Literal["weekday", "weekend"]
AnomalyKind = Literal["no_morning_water", "no_usage_all_day", "night_flow"]
DEFAULT_THRESHOLD = 0.995                         # GaussianScorer score >= 이면 이상
GRACE_PERIOD = 3                                  # 키당 최소 학습 샘플 수

@dataclass(frozen=True)
class Reading:
    sensor_id: str
    ts: datetime        # tz-aware (TZ), 5분 격자
    value: float        # 그 5분 동안 리터, >= 0

@dataclass(frozen=True)
class HourlyUsage:
    sensor_id: str
    hour_start: datetime  # tz-aware, 정시
    value: float          # 리터 합

@dataclass(frozen=True)
class Anomaly:
    sensor_id: str
    window_start: datetime
    window_end: datetime
    score: float
    expected: float      # 모델이 학습한 평균
    actual: float        # 창 합계
    reason: str          # f"{window} usage {actual:.1f}L, usual {expected:.1f}L"

@dataclass(frozen=True)
class InjectedAnomaly:
    kind: AnomalyKind
    day: date

@dataclass(frozen=True)
class Scenario:
    sensor_id: str
    start: date          # 00:00 TZ 부터
    days: int
    seed: int
    learn_days: int      # 이 일수 동안은 Anomaly 를 내지 않는다
    anomalies: tuple[InjectedAnomaly, ...] = ()

    @property
    def start_dt(self) -> datetime: return datetime.combine(self.start, datetime.min.time(), TZ)
    @property
    def end_dt(self) -> datetime: return self.start_dt + timedelta(days=self.days)
    @property
    def learn_until(self) -> datetime: return self.start_dt + timedelta(days=self.learn_days)

DEFAULT_SCENARIO = Scenario(
    sensor_id="water_main", start=date(2026, 10, 5), days=28, seed=42, learn_days=14,
    anomalies=(
        InjectedAnomaly("no_morning_water", date(2026, 10, 23)),   # 금
        InjectedAnomaly("no_usage_all_day", date(2026, 10, 28)),   # 수
        InjectedAnomaly("night_flow", date(2026, 10, 31)),         # 토
    ),
)

def day_type(dt: datetime) -> DayType:            # Mon-Fri → "weekday", Sat-Sun → "weekend"
    return "weekend" if dt.weekday() >= 5 else "weekday"

def window_of(dt: datetime) -> WindowName:        # dt.hour 로 WINDOWS 조회
    for name, (lo, hi) in WINDOWS.items():
        if lo <= dt.hour < hi:
            return name
    raise ValueError(f"hour out of range: {dt.hour}")

def window_start(dt: datetime) -> datetime:       # 그 창의 시작 정시 (tz 유지)
    lo, _ = WINDOWS[window_of(dt)]
    return dt.replace(hour=lo, minute=0, second=0, microsecond=0)

class Store(Protocol):
    def insert_readings(self, readings: Iterable[Reading]) -> int: ...
    def count_readings(self, sensor_id: str | None = None) -> int: ...
    def hourly_usage(self, sensor_id: str, start: datetime, end: datetime) -> list[HourlyUsage]: ...
    def insert_anomalies(self, anomalies: Iterable[Anomaly]) -> int: ...
    def list_anomalies(self, sensor_id: str) -> list[Anomaly]: ...
    def close(self) -> None: ...

class Detector(Protocol):
    def update(self, usage: HourlyUsage) -> Anomaly | None: ...
    # 시간별 사용량을 창에 누적하고, 창이 닫힐 때(다음 창 첫 시간이 들어올 때) 점수→판단→학습.
    # 마지막 창은 flush() 로 닫는다.
    def flush(self) -> Anomaly | None: ...
