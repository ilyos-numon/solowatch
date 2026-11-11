"""알림 문장·일일 요약 조립. 집 밖으로 나가는 텍스트는 여기서만 만든다."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from solowatch.contracts import TZ, Anomaly, HourlyUsage, window_of
from solowatch.contracts_mvp import (
    SENSOR_LABEL_KO,
    WINDOW_LABEL_KO,
    AlertPayload,
    DailyReportPayload,
    SensorSpec,
)

ALERT_PREFIX = "이상 가능성 있음"
ALERT_SUFFIX = "평소와 다릅니다"
SEP = " · "


def _label(sensor_id: str) -> str:
    return SENSOR_LABEL_KO.get(sensor_id, sensor_id)


def _describe(a: Anomaly, spec: SensorSpec | None) -> str:
    window = window_of(a.window_start.astimezone(TZ))
    is_water = spec.kind == "water" if spec is not None else a.sensor_id.startswith("water")
    if is_water:
        if a.actual < a.expected:
            return "물 사용 없음"
        if window == "night" and a.actual > a.expected:
            return "밤새 물 흐름"
    elif a.sensor_id == "plug_light" and window == "night" and a.actual > a.expected:
        return "거실등 밤새 켜짐"
    elif a.sensor_id == "plug_tv" and window == "evening" and a.actual < a.expected:
        return "저녁 TV 사용 없음"
    elif a.sensor_id == "plug_fridge" and a.actual == 0:
        return "냉장고 전원 없음"
    return f"{_label(a.sensor_id)} 평소와 다름"


def compose_alert(anomalies: Iterable[Anomaly], sensors: Mapping[str, SensorSpec],
                  household_id: str) -> list[AlertPayload]:
    groups: dict[object, list[Anomaly]] = {}
    for a in anomalies:
        groups.setdefault(a.window_start, []).append(a)
    payloads: list[AlertPayload] = []
    for group in sorted(groups.values(), key=lambda g: g[0].window_start):
        first = group[0]
        window = window_of(first.window_start.astimezone(TZ))
        descriptions = [_describe(a, sensors.get(a.sensor_id)) for a in group]
        sentence = SEP.join([ALERT_PREFIX, f"{WINDOW_LABEL_KO[window]} {descriptions[0]}",
                             *descriptions[1:], ALERT_SUFFIX])
        details = {"sensors": [{"sensor_id": a.sensor_id, "reason": a.reason,
                                "expected": float(a.expected), "actual": float(a.actual)}
                               for a in group]}
        payloads.append(AlertPayload(household_id=household_id, kind="anomaly",
                                     window_start=first.window_start, window_end=first.window_end,
                                     sentence=sentence, details=details))
    return payloads


def _period(hour: int) -> str:
    if hour < 6:
        return "밤"
    if hour < 12:
        return "아침"
    if hour < 18:
        return "낮"
    return "저녁"


def _first_activity_text(sensor_id: str, spec: SensorSpec, hour: int) -> str | None:
    if sensor_id == "plug_fridge":
        return None
    if sensor_id == "plug_light":
        return f"거실등 {hour}시 켬"
    if spec.kind == "water":
        return f"{_period(hour)} {hour}시 물 사용"
    if sensor_id == "plug_tv":
        return f"{_period(hour)} {hour}시 TV 켬"
    return f"{_period(hour)} {hour}시 {_label(sensor_id)} 켬"


def compose_daily(day: date, usage_by_sensor: Mapping[str, list[HourlyUsage]],
                  sensors: Mapping[str, SensorSpec], household_id: str,
                  alert_count: int) -> DailyReportPayload:
    rhythm: dict[str, list[bool]] = {}
    first_events: dict[str, str] = {}
    firsts: list[tuple[int, int, str]] = []   # (hour, sensor order, text)
    for order, (sensor_id, spec) in enumerate(sensors.items()):
        flags = [False] * 24
        for u in usage_by_sensor.get(sensor_id, []):
            local = u.hour_start.astimezone(TZ)
            if local.date() == day and u.value >= spec.active_threshold:
                flags[local.hour] = True
        rhythm[sensor_id] = flags
        if True in flags:
            hour = flags.index(True)
            first_events[sensor_id] = f"{hour:02d}:00"
            text = _first_activity_text(sensor_id, spec, hour)
            if text is not None:
                firsts.append((hour, order, text))
    if alert_count > 0:
        sentence = f"오늘 알림 {alert_count}건{SEP}앱에서 확인해 주세요"
    else:
        sentence = SEP.join(["오늘 리듬 정상", *(t for _, _, t in sorted(firsts))])
    return DailyReportPayload(household_id=household_id, day=day, sentence=sentence,
                              rhythm=rhythm, first_events=first_events)
