# src/solowatch/contracts_demo.py — S1 이후 동결. 변경 = BLOCKED.
from __future__ import annotations

from dataclasses import dataclass, field  # noqa: F401
from datetime import date
from typing import Any, Literal, Protocol

from solowatch.contracts_mvp import DEMO_HOUSEHOLD_ID  # noqa: F401 (재노출)

DemoEventKind = Literal["normal", "no_morning_water", "fridge_off", "light_all_night", "night_flow"]
DEMO_EVENT_KINDS: tuple[DemoEventKind, ...] = (
    "normal", "no_morning_water", "fridge_off", "light_all_night", "night_flow")
DEMO_EVENT_LABEL_KO: dict[str, str] = {
    "normal": "평범한 하루", "no_morning_water": "아침 물 없음", "fridge_off": "냉장고 전원 끊김",
    "light_all_night": "밤새 거실등", "night_flow": "밤중 물 흐름"}
# 이벤트가 영향을 주는 (sensor_id, window) — 점수 전후 표시용. normal 은 ()
DEMO_EVENT_FOCUS: dict[str, tuple[tuple[str, str], ...]] = {
    "normal": (), "no_morning_water": (("water_main", "morning"),),
    "fridge_off": (("plug_fridge", "night"), ("plug_fridge", "morning"),
                   ("plug_fridge", "afternoon"), ("plug_fridge", "evening")),
    "light_all_night": (("plug_light", "night"),), "night_flow": (("water_main", "night"),)}
DEMO_START = date(2026, 11, 2)          # 가상 시계 시작(월). 이전 28 일 = DEFAULT_HOME, 초기화 때 미리 넣는다
DEMO_MAX_DAYS = 14                       # day_index 가 이 값에 닿으면 다음 조작 전 자동 초기화
DEMO_SEED_BASE = 1080                    # 가상 날 n 의 seed = DEMO_SEED_BASE + n (평범한 날 0..13 오경보 0 으로 검증된 값)
DEMO_AWAY: tuple[date, date] = (date(2026, 10, 26), date(2026, 10, 27))
DEMO_AWAY_NOTE = "demo-seed"
DEMO_FAMILY_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-000000000001"   # seed.sql 의 family@example.com
DEMO_FAMILY_EMAIL = "family@example.com"
OUTBOX_LIMIT = 50
RECENT_SLOTS = 288                       # 집 안 그래프: 마지막 24 h, 5 분 슬롯
ENV_SERVICE_ROLE_KEY = "SUPABASE_SERVICE_ROLE_KEY"
ENV_WEB_DIST = "SOLOWATCH_WEB_DIST"      # 정적 파일 디렉토리. 비어 있으면 API 만 서빙
ENV_PORT = "PORT"                        # Cloud Run 규약. 기본 8845
DEMO_API_PREFIX = "/api/demo"


@dataclass(frozen=True)
class ScoreEntry:
    sensor_id: str
    window: str          # WindowName
    day_type: str        # DayType
    score: float         # river GaussianScorer.score_one(None, actual) — 그 창을 학습하기 전 값
    expected: float      # scorer.gaussian.mu
    actual: float        # 창 합계 (L 또는 watt-slot)
    flagged: bool        # Daemon 이 이 창을 Anomaly 로 기록했는가
    def to_dict(self) -> dict[str, Any]:   # 필드 이름 그대로
        return {"sensor_id": self.sensor_id, "window": self.window, "day_type": self.day_type,
                "score": self.score, "expected": self.expected, "actual": self.actual,
                "flagged": self.flagged}


@dataclass(frozen=True)
class OutboxEntry:
    at: str                              # 서버 실제 시각 ISO
    direction: Literal["out", "in"]      # out: 집 → Supabase, in: Supabase → 집
    table: str                           # "alerts" | "daily_reports" | "alert_feedback" | "away_periods"
    summary: str                         # 한 줄. alerts: 문장 / daily_reports: "일일 요약 2026-11-02 · <문장>" / alert_feedback: "괜찮았음 · 아침 창 평소 30.1 → 27.4 L" / away_periods: "외출 10-26 ~ 10-27"
    row: dict[str, Any]                  # to_row() 결과 또는 fetch 결과(dict). 5 분 값·시간별 값 없음
    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at, "direction": self.direction, "table": self.table,
                "summary": self.summary, "row": self.row}


@dataclass(frozen=True)
class InjectResult:
    kind: DemoEventKind
    day: str                             # "YYYY-MM-DD"
    day_type: str                        # "weekday" | "weekend"
    readings: int                        # 넣은 reading 수 (4 센서 × 288 = 1152)
    alerts: list[dict[str, Any]]         # [{"remote_id": str, "sentence": str, "window_start": ISO}] 이 날 창의 anomaly 알림만
    scores: list[ScoreEntry]             # 4 센서 × 4 창 = 16 항목 (주입 전 점수)
    previous_scores: list[ScoreEntry]    # 같은 kind 의 직전 주입 scores (없으면 [])
    daily_sent: bool
    auto_reset: bool                     # 이 조작 직전에 DEMO_MAX_DAYS 로 초기화했는가
    def to_dict(self) -> dict[str, Any]:   # scores/previous_scores 는 to_dict 목록
        return {"kind": self.kind, "day": self.day, "day_type": self.day_type,
                "readings": self.readings, "alerts": self.alerts,
                "scores": [s.to_dict() for s in self.scores],
                "previous_scores": [s.to_dict() for s in self.previous_scores],
                "daily_sent": self.daily_sent, "auto_reset": self.auto_reset}


@dataclass(frozen=True)
class DemoState:
    ready: bool
    virtual_now: str                     # ISO(+09:00). 다음 처리할 날의 00:00
    day_index: int                       # 0 = 초기화 직후
    household_id: str
    readings_total: int
    recent: dict[str, list[list[Any]]]   # sensor_id → [[ts_iso, value], ...] 마지막 RECENT_SLOTS 개 (집 안 전용)
    outbox: list[OutboxEntry]            # 최신이 앞, 최대 OUTBOX_LIMIT
    last_inject: InjectResult | None
    history: list[dict[str, Any]]        # [{"day": "YYYY-MM-DD", "kind": str, "alerts": int}] 초기화 이후 순서대로
    error: str | None
    def to_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "virtual_now": self.virtual_now, "day_index": self.day_index,
                "household_id": self.household_id, "readings_total": self.readings_total,
                "recent": self.recent, "outbox": [o.to_dict() for o in self.outbox],
                "last_inject": self.last_inject.to_dict() if self.last_inject else None,
                "history": self.history, "error": self.error}


class VirtualHomeLike(Protocol):
    def reset(self) -> DemoState: ...
    def inject(self, kind: DemoEventKind) -> InjectResult: ...   # 알 수 없는 kind → ValueError
    def state(self) -> DemoState: ...
    def close(self) -> None: ...
