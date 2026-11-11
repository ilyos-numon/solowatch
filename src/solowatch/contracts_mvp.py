# src/solowatch/contracts_mvp.py — S1 이후 동결. 변경 = BLOCKED.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from solowatch.contracts import TZ, Anomaly, InjectedAnomaly, Scenario  # noqa: F401 (Anomaly 재노출)

SensorKind = Literal["water", "plug"]
Unit = Literal["L", "W"]
EventKind = Literal["no_morning_water", "no_usage_all_day", "night_flow",
                    "light_all_night", "no_tv_evening", "fridge_off", "different_morning"]
WATER_EVENTS: frozenset[str] = frozenset({"no_morning_water", "no_usage_all_day", "night_flow"})
Verdict = Literal["ok", "checking", "confirmed", "missed"]
AlertKind = Literal["anomaly", "daily_ok"]

DEMO_HOUSEHOLD_ID = "11111111-1111-4111-8111-111111111111"
DEMO_HOUSEHOLD_SLUG = "home-demo"
DEMO_HOUSEHOLD_NAME = "어머니 댁"
TOPIC_TEMPLATE = "solowatch/{slug}/{sensor_id}/state"
MIN_DEVIATION_W = 300.0            # watt-slot (5분 평균 W 의 창 합) = 25 Wh
SENSOR_LABEL_KO = {"water_main": "물", "plug_fridge": "냉장고", "plug_tv": "TV", "plug_light": "거실등"}
WINDOW_LABEL_KO = {"night": "밤 (0~6시)", "morning": "아침 (6~12시)",
                   "afternoon": "오후 (12~18시)", "evening": "저녁 (18~24시)"}
ENV_SUPABASE_URL = "SUPABASE_URL"
ENV_SUPABASE_ANON_KEY = "SUPABASE_ANON_KEY"
ENV_DEVICE_EMAIL = "SOLOWATCH_DEVICE_EMAIL"
ENV_DEVICE_PASSWORD = "SOLOWATCH_DEVICE_PASSWORD"
ENV_APPRISE_URLS = "SOLOWATCH_APPRISE_URLS"     # 쉼표 구분, 비어 있으면 Apprise 미사용

def native_topic(slug: str, sensor_id: str) -> str:
    return TOPIC_TEMPLATE.format(slug=slug, sensor_id=sensor_id)

@dataclass(frozen=True)
class SensorSpec:
    sensor_id: str
    kind: SensorKind
    unit: Unit
    min_deviation: float        # L: 5.0 / W: 300.0
    active_threshold: float     # 시간 합이 이 값 이상이면 "활동" (리듬 요약용)
    topic: str                  # MQTT 토픽 (와일드카드 허용)
    value_path: str = "value"   # 점 표기 JSON 경로. 예: "ENERGY.Power", "power"
    ts_path: str = "ts"         # 없으면 수신 시각

DEFAULT_SENSORS: tuple[SensorSpec, ...] = (
    SensorSpec("water_main", "water", "L", 5.0, 0.5, native_topic(DEMO_HOUSEHOLD_SLUG, "water_main")),
    SensorSpec("plug_fridge", "plug", "W", MIN_DEVIATION_W, 1.0, native_topic(DEMO_HOUSEHOLD_SLUG, "plug_fridge")),
    SensorSpec("plug_tv", "plug", "W", MIN_DEVIATION_W, 60.0, native_topic(DEMO_HOUSEHOLD_SLUG, "plug_tv")),
    SensorSpec("plug_light", "plug", "W", MIN_DEVIATION_W, 30.0, native_topic(DEMO_HOUSEHOLD_SLUG, "plug_light")),
)

@dataclass(frozen=True)
class InjectedEvent:
    kind: EventKind
    day: date

@dataclass(frozen=True)
class AwayPeriod:
    start_date: date
    end_date: date              # inclusive
    note: str = ""
    id: str = ""
    def covers(self, dt: datetime) -> bool:
        d = dt.astimezone(TZ).date()
        return self.start_date <= d <= self.end_date

@dataclass(frozen=True)
class HomeScenario:
    household_id: str
    slug: str
    start: date
    days: int
    seed: int
    learn_days: int
    sensors: tuple[SensorSpec, ...] = DEFAULT_SENSORS
    events: tuple[InjectedEvent, ...] = ()
    away: tuple[tuple[date, date], ...] = ()
    @property
    def start_dt(self) -> datetime: return datetime.combine(self.start, datetime.min.time(), TZ)
    @property
    def end_dt(self) -> datetime: return self.start_dt + timedelta(days=self.days)
    @property
    def learn_until(self) -> datetime: return self.start_dt + timedelta(days=self.learn_days)
    def away_periods(self) -> tuple[AwayPeriod, ...]:
        return tuple(AwayPeriod(s, e, "외출") for s, e in self.away)
    def water_scenario(self) -> Scenario:   # 수도 이벤트만 InjectedAnomaly 로; different_morning → no_morning_water
        kinds = {"no_morning_water": "no_morning_water", "no_usage_all_day": "no_usage_all_day",
                 "night_flow": "night_flow", "different_morning": "no_morning_water"}
        return Scenario("water_main", self.start, self.days, self.seed, self.learn_days,
                        tuple(InjectedAnomaly(kinds[e.kind], e.day) for e in self.events if e.kind in kinds))  # type: ignore[arg-type]

DEFAULT_HOME = HomeScenario(
    household_id=DEMO_HOUSEHOLD_ID, slug=DEMO_HOUSEHOLD_SLUG,
    start=date(2026, 10, 5), days=28, seed=42, learn_days=14,
    events=(InjectedEvent("light_all_night", date(2026, 10, 21)),
            InjectedEvent("no_morning_water", date(2026, 10, 23)),
            InjectedEvent("no_tv_evening", date(2026, 10, 25)),
            InjectedEvent("no_usage_all_day", date(2026, 10, 28)),
            InjectedEvent("fridge_off", date(2026, 10, 29)),
            InjectedEvent("different_morning", date(2026, 10, 30)),
            InjectedEvent("night_flow", date(2026, 10, 31))),
    away=((date(2026, 10, 26), date(2026, 10, 27)),),
)

@dataclass(frozen=True)
class AlertPayload:
    household_id: str
    kind: AlertKind
    window_start: datetime
    window_end: datetime
    sentence: str
    details: dict[str, Any] = field(default_factory=dict)  # {"sensors": [{"sensor_id","reason","expected","actual"}]}
    status: str = "open"
    def to_row(self) -> dict[str, Any]:   # 키 정확히: household_id, kind, window_start(ISO), window_end(ISO), sentence, details, status
        return {"household_id": self.household_id, "kind": self.kind,
                "window_start": self.window_start.isoformat(), "window_end": self.window_end.isoformat(),
                "sentence": self.sentence, "details": self.details, "status": self.status}

@dataclass(frozen=True)
class DailyReportPayload:
    household_id: str
    day: date
    sentence: str
    rhythm: dict[str, list[bool]]          # sensor_id → 24개
    first_events: dict[str, str]           # sensor_id → "06:00"
    def to_row(self) -> dict[str, Any]:   # 키: household_id, day(ISO), sentence, rhythm, first_events
        return {"household_id": self.household_id, "day": self.day.isoformat(), "sentence": self.sentence,
                "rhythm": self.rhythm, "first_events": self.first_events}

@dataclass(frozen=True)
class FeedbackRow:
    id: str
    alert_id: str | None
    verdict: Verdict
    day: date | None
    note: str
    created_at: datetime

@dataclass(frozen=True)
class LoggedAlert:
    id: str
    payload: AlertPayload
    created_at: datetime
    sent_at: datetime | None
    remote_id: str | None

@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str = ""
    password: str = ""

@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    anon_key: str
    device_email: str
    device_password: str

@dataclass(frozen=True)
class DetectorConfig:
    learn_days: int = 14
    threshold: float = 0.995
    tick_seconds: int = 60
    daily_report_hour: int = 20

@dataclass(frozen=True)
class AppConfig:
    household_id: str
    slug: str
    name: str
    mqtt: MqttConfig
    store_path: str
    detector: DetectorConfig
    supabase: SupabaseConfig | None        # None 이면 Supabase 싱크 없음 (단위 테스트용)
    apprise_urls: tuple[str, ...]
    sensors: tuple[SensorSpec, ...]
    install_start: date | None = None      # 학습 시작일. None → 첫 reading 의 로컬 날짜

class ConfigError(ValueError):
    """설정 파일 또는 env 누락. str(e) 에 누락 이름이 들어간다."""
