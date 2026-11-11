from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from solowatch.contracts import SLOT, TZ, Anomaly, Reading
from solowatch.contracts_mvp import DEMO_HOUSEHOLD_ID, AlertPayload, AwayPeriod, FeedbackRow
from solowatch.store import SqliteStore

START = datetime(2026, 10, 5, tzinfo=TZ)
END = datetime(2026, 11, 2, tzinfo=TZ)
SENSOR = "water_main"


def grid_readings(value: float = 0.5) -> list[Reading]:
    n = int((END - START) / SLOT)
    return [Reading(SENSOR, START + i * SLOT, value) for i in range(n)]


def test_fresh_file_creates_tables(tmp_path: Path) -> None:
    db = tmp_path / "new.db"
    assert not db.exists()
    store = SqliteStore(str(db))
    try:
        assert store.count_readings() == 0
    finally:
        store.close()
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"readings", "anomalies"} <= names


def test_double_insert_is_idempotent() -> None:
    readings = grid_readings()
    assert len(readings) == 8064
    store = SqliteStore(":memory:")
    assert store.insert_readings(readings) == 8064
    assert store.insert_readings(readings) == 0
    assert store.count_readings() == 8064
    assert store.count_readings(SENSOR) == 8064
    assert store.count_readings("other") == 0
    store.close()


def test_hourly_usage_covers_672_hours_and_sum_matches() -> None:
    readings = grid_readings(0.25)
    store = SqliteStore(":memory:")
    store.insert_readings(readings)
    rows = store.hourly_usage(SENSOR, START, END)
    assert len(rows) == 672
    assert abs(sum(r.value for r in rows) - sum(r.value for r in readings)) < 1e-6
    assert rows[0].hour_start == START
    assert rows[-1].hour_start == END - timedelta(hours=1)
    assert all(r.sensor_id == SENSOR for r in rows)
    assert all(abs(r.value - 3.0) < 1e-9 for r in rows)  # 12 slots x 0.25
    hours = [r.hour_start for r in rows]
    assert hours == sorted(hours)
    store.close()


def test_hourly_usage_fills_missing_hours_with_zero() -> None:
    store = SqliteStore(":memory:")
    store.insert_readings([Reading(SENSOR, START + timedelta(hours=2, minutes=5), 4.0)])
    rows = store.hourly_usage(SENSOR, START, START + timedelta(hours=4))
    assert [r.value for r in rows] == [0.0, 0.0, 4.0, 0.0]
    store.close()


def test_anomaly_round_trip() -> None:
    a1 = Anomaly(SENSOR, datetime(2026, 10, 23, 6, tzinfo=TZ), datetime(2026, 10, 23, 12, tzinfo=TZ),
                 0.999, 30.5, 0.0, "morning usage 0.0L, usual 30.5L")
    a0 = Anomaly(SENSOR, datetime(2026, 10, 20, 0, tzinfo=TZ), datetime(2026, 10, 20, 6, tzinfo=TZ),
                 0.997, 6.0, 60.0, "night usage 60.0L, usual 6.0L")
    store = SqliteStore(":memory:")
    assert store.insert_anomalies([a1, a0]) == 2
    assert store.list_anomalies(SENSOR) == [a0, a1]
    assert store.list_anomalies("other") == []
    store.close()


def _alert_payload() -> tuple[AlertPayload, list[Anomaly]]:
    ws = datetime(2026, 10, 23, 6, tzinfo=TZ)
    we = ws + timedelta(hours=6)
    anomalies = [
        Anomaly("water_main", ws, we, 0.999, 25.0, 0.0, "morning usage 0.0L, usual 25.0L"),
        Anomaly("plug_tv", ws, we, 0.998, 900.0, 0.0, "morning power 0.0Ws, usual 900.0Ws"),
    ]
    payload = AlertPayload(
        household_id=DEMO_HOUSEHOLD_ID, kind="anomaly", window_start=ws, window_end=we,
        sentence="오늘 아침 물 사용이 없었어요.",
        details={"sensors": [{"sensor_id": "water_main", "reason": "x", "expected": 25.0,
                              "actual": 0.0}]},
    )
    return payload, anomalies


def test_ops_tables_created(tmp_path: Path) -> None:
    db = tmp_path / "ops.db"
    SqliteStore(str(db)).close()
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"alerts_log", "alert_anomalies", "feedback", "away_periods", "cursors"} <= names


def test_alert_log_round_trip() -> None:
    store = SqliteStore(":memory:")
    payload, anomalies = _alert_payload()
    alert_id = store.log_alert(payload, anomalies)
    assert str(uuid.UUID(alert_id)) == alert_id
    assert store.anomalies_for_alert(alert_id) == anomalies
    unsent = store.unsent_alerts()
    assert [a.id for a in unsent] == [alert_id]
    assert unsent[0].payload == payload
    assert unsent[0].sent_at is None and unsent[0].remote_id is None
    store.mark_sent(alert_id, alert_id)
    assert store.unsent_alerts() == []
    logged = store.list_alert_log()
    assert len(logged) == 1
    assert logged[0].remote_id == alert_id and logged[0].sent_at is not None
    assert logged[0].payload == payload
    store.close()


def test_feedback_upsert_and_apply() -> None:
    store = SqliteStore(":memory:")
    created = datetime(2026, 10, 23, 13, tzinfo=TZ)
    rows = [
        FeedbackRow("f1", "a1", "ok", None, "", created),
        FeedbackRow("f2", None, "missed", date(2026, 10, 24), "넘어지셨음", created),
    ]
    assert store.upsert_feedback(rows) == 2
    assert store.upsert_feedback(rows) == 0
    assert store.unapplied_feedback() == rows
    store.mark_applied("f1")
    assert store.unapplied_feedback() == rows[1:]
    assert store.list_feedback() == rows
    store.close()


def test_away_replace_and_list() -> None:
    store = SqliteStore(":memory:")
    first = [AwayPeriod(date(2026, 10, 26), date(2026, 10, 27), "외출", "p1")]
    store.replace_away(first)
    assert store.list_away() == first
    second = [AwayPeriod(date(2026, 11, 1), date(2026, 11, 2), "병원", "p2")]
    store.replace_away(second)
    assert store.list_away() == second
    store.close()


def test_cursor_persists_across_reopen(tmp_path: Path) -> None:
    db = str(tmp_path / "cur.db")
    store = SqliteStore(db)
    assert store.get_cursor("hour:water_main") is None
    store.set_cursor("hour:water_main", "2026-10-30T06:00:00+09:00")
    store.set_cursor("hour:water_main", "2026-10-30T12:00:00+09:00")
    store.close()
    store = SqliteStore(db)
    assert store.get_cursor("hour:water_main") == "2026-10-30T12:00:00+09:00"
    store.close()


def test_sensor_ids_lists_four_sorted() -> None:
    store = SqliteStore(":memory:")
    ids = ["water_main", "plug_tv", "plug_light", "plug_fridge"]
    store.insert_readings(Reading(s, START, 1.0) for s in ids)
    assert store.sensor_ids() == sorted(ids)
    store.close()
