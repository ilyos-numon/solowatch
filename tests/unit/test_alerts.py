from __future__ import annotations

from datetime import date, datetime, timedelta

from solowatch.alerts import compose_alert, compose_daily
from solowatch.contracts import TZ, Anomaly, HourlyUsage
from solowatch.contracts_mvp import DEFAULT_SENSORS, DEMO_HOUSEHOLD_ID

SENSORS = {s.sensor_id: s for s in DEFAULT_SENSORS}
DAY = date(2026, 10, 30)


def _at(hour: int, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=TZ)


def _anomaly(sensor_id: str, start_hour: int, expected: float, actual: float) -> Anomaly:
    return Anomaly(sensor_id, _at(start_hour), _at(start_hour) + timedelta(hours=6), 0.999,
                   expected, actual, f"usage {actual:.1f}, usual {expected:.1f}")


def test_different_morning_two_payloads_and_exact_sentence() -> None:
    anomalies = [_anomaly("water_main", 6, 25.0, 0.0), _anomaly("plug_light", 0, 0.0, 720.0)]
    payloads = compose_alert(anomalies, SENSORS, DEMO_HOUSEHOLD_ID)
    assert len(payloads) == 2
    by_start = {p.window_start: p for p in payloads}
    morning = by_start[_at(6)]
    assert morning.sentence == "이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다"
    assert morning.kind == "anomaly"
    assert morning.household_id == DEMO_HOUSEHOLD_ID
    assert morning.window_end == _at(12)
    night = by_start[_at(0)]
    assert night.sentence == "이상 가능성 있음 · 밤 (0~6시) 거실등 밤새 켜짐 · 평소와 다릅니다"
    assert [p.window_start for p in payloads] == sorted(by_start)


def test_same_window_grouped_into_one_payload_with_details() -> None:
    anomalies = [_anomaly("water_main", 0, 0.5, 40.0), _anomaly("plug_light", 0, 0.0, 720.0)]
    payloads = compose_alert(anomalies, SENSORS, DEMO_HOUSEHOLD_ID)
    assert len(payloads) == 1
    p = payloads[0]
    assert p.sentence == "이상 가능성 있음 · 밤 (0~6시) 밤새 물 흐름 · 거실등 밤새 켜짐 · 평소와 다릅니다"
    assert p.details == {"sensors": [
        {"sensor_id": "water_main", "reason": anomalies[0].reason, "expected": 0.5, "actual": 40.0},
        {"sensor_id": "plug_light", "reason": anomalies[1].reason, "expected": 0.0, "actual": 720.0},
    ]}


def test_description_rules() -> None:
    cases = [
        (_anomaly("plug_tv", 18, 3000.0, 0.0), "저녁 (18~24시) 저녁 TV 사용 없음"),
        (_anomaly("plug_fridge", 12, 900.0, 0.0), "오후 (12~18시) 냉장고 전원 없음"),
        (_anomaly("plug_tv", 6, 0.0, 2000.0), "아침 (6~12시) TV 평소와 다름"),
        (_anomaly("water_main", 12, 10.0, 80.0), "오후 (12~18시) 물 평소와 다름"),
        (_anomaly("plug_light", 18, 600.0, 0.0), "저녁 (18~24시) 거실등 평소와 다름"),
    ]
    for anomaly, middle in cases:
        [p] = compose_alert([anomaly], SENSORS, DEMO_HOUSEHOLD_ID)
        assert p.sentence == f"이상 가능성 있음 · {middle} · 평소와 다릅니다"


def test_no_anomalies_no_payloads() -> None:
    assert compose_alert([], SENSORS, DEMO_HOUSEHOLD_ID) == []


def test_alert_to_row_has_exactly_seven_keys() -> None:
    [p] = compose_alert([_anomaly("water_main", 6, 25.0, 0.0)], SENSORS, DEMO_HOUSEHOLD_ID)
    row = p.to_row()
    assert set(row) == {"household_id", "kind", "window_start", "window_end", "sentence",
                        "details", "status"}
    assert len(row) == 7


def _usage(sensor_id: str, values: dict[int, float]) -> list[HourlyUsage]:
    return [HourlyUsage(sensor_id, _at(h), values.get(h, 0.0)) for h in range(24)]


def _normal_day() -> dict[str, list[HourlyUsage]]:
    return {
        "water_main": _usage("water_main", {6: 8.0, 7: 5.0, 12: 3.0, 19: 6.0}),
        "plug_fridge": _usage("plug_fridge", {h: 600.0 for h in range(24)}),
        "plug_tv": _usage("plug_tv", {19: 1200.0, 20: 1200.0}),
        "plug_light": _usage("plug_light", {18: 120.0, 19: 120.0, 20: 120.0}),
    }


def test_normal_day_sentence_and_rhythm() -> None:
    p = compose_daily(DAY, _normal_day(), SENSORS, DEMO_HOUSEHOLD_ID, alert_count=0)
    assert p.sentence == "오늘 리듬 정상 · 아침 6시 물 사용 · 거실등 18시 켬 · 저녁 19시 TV 켬"
    assert p.rhythm["water_main"][6] is True
    assert p.rhythm["water_main"][5] is False
    assert all(len(v) == 24 for v in p.rhythm.values())
    assert set(p.rhythm) == set(SENSORS)
    assert p.first_events["water_main"] == "06:00"
    assert p.first_events["plug_tv"] == "19:00"
    assert p.day == DAY
    assert p.household_id == DEMO_HOUSEHOLD_ID


def test_daytime_prefix() -> None:
    usage = {"water_main": _usage("water_main", {13: 4.0})}
    p = compose_daily(DAY, usage, SENSORS, DEMO_HOUSEHOLD_ID, alert_count=0)
    assert p.sentence == "오늘 리듬 정상 · 낮 13시 물 사용"


def test_alert_count_sentence() -> None:
    p = compose_daily(DAY, _normal_day(), SENSORS, DEMO_HOUSEHOLD_ID, alert_count=1)
    assert p.sentence == "오늘 알림 1건 · 앱에서 확인해 주세요"
    p3 = compose_daily(DAY, _normal_day(), SENSORS, DEMO_HOUSEHOLD_ID, alert_count=3)
    assert p3.sentence == "오늘 알림 3건 · 앱에서 확인해 주세요"


def test_daily_row_has_only_booleans_and_strings() -> None:
    p = compose_daily(DAY, _normal_day(), SENSORS, DEMO_HOUSEHOLD_ID, alert_count=0)
    row = p.to_row()
    assert set(row) == {"household_id", "day", "sentence", "rhythm", "first_events"}
    for flags in row["rhythm"].values():
        assert all(isinstance(f, bool) for f in flags)
    assert all(isinstance(v, str) for v in row["first_events"].values())
