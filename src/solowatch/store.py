from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from solowatch.contracts import TZ, Anomaly, HourlyUsage, Reading, Store
from solowatch.contracts_mvp import AlertPayload, AwayPeriod, FeedbackRow, LoggedAlert

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings(sensor_id TEXT NOT NULL, ts TEXT NOT NULL, value REAL NOT NULL,
  PRIMARY KEY(sensor_id, ts));
CREATE TABLE IF NOT EXISTS anomalies(sensor_id TEXT NOT NULL, window_start TEXT NOT NULL,
  window_end TEXT NOT NULL, score REAL NOT NULL, expected REAL NOT NULL, actual REAL NOT NULL,
  reason TEXT NOT NULL, PRIMARY KEY(sensor_id, window_start));
CREATE TABLE IF NOT EXISTS alerts_log(id TEXT PRIMARY KEY, kind TEXT NOT NULL, window_start TEXT NOT NULL,
  window_end TEXT NOT NULL, sentence TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL,
  sent_at TEXT, remote_id TEXT);
CREATE TABLE IF NOT EXISTS alert_anomalies(alert_id TEXT NOT NULL, sensor_id TEXT NOT NULL,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL, score REAL NOT NULL, expected REAL NOT NULL,
  actual REAL NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(alert_id, sensor_id, window_start));
CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY, alert_id TEXT, verdict TEXT NOT NULL, day TEXT,
  note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, applied_at TEXT);
CREATE TABLE IF NOT EXISTS away_periods(id TEXT PRIMARY KEY, start_date TEXT NOT NULL,
  end_date TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS cursors(name TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_ALERT_COLS = "id, kind, window_start, window_end, sentence, details, created_at, sent_at, remote_id"
_FEEDBACK_COLS = "id, alert_id, verdict, day, note, created_at"

_HOUR = timedelta(hours=1)


def _iso(dt: datetime) -> str:
    return dt.astimezone(TZ).isoformat()


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(TZ)


def _now() -> str:
    return _iso(datetime.now(TZ))


def _logged_alert(row: tuple[Any, ...]) -> LoggedAlert:
    # `details` column holds the payload fields that have no column of their own.
    aid, kind, ws, we, sentence, details, created, sent, remote = row
    extra = json.loads(details)
    payload = AlertPayload(
        household_id=extra["household_id"], kind=kind, window_start=_parse(ws),
        window_end=_parse(we), sentence=sentence, details=extra["details"], status=extra["status"],
    )
    return LoggedAlert(aid, payload, _parse(created), _parse(sent) if sent else None, remote)


def _feedback(row: tuple[Any, ...]) -> FeedbackRow:
    fid, alert_id, verdict, day, note, created = row
    return FeedbackRow(fid, alert_id, verdict, date.fromisoformat(day) if day else None, note,
                       _parse(created))


class SqliteStore(Store):
    def __init__(self, path: str) -> None:
        self._con = sqlite3.connect(path)
        self._con.executescript(_SCHEMA)
        self._con.commit()

    def _insert(self, sql: str, rows: Iterable[tuple[object, ...]]) -> int:
        before = self._con.total_changes
        with self._con:
            self._con.executemany(sql, rows)
        return self._con.total_changes - before

    def insert_readings(self, readings: Iterable[Reading]) -> int:
        return self._insert(
            "INSERT OR IGNORE INTO readings(sensor_id, ts, value) VALUES (?, ?, ?)",
            ((r.sensor_id, _iso(r.ts), r.value) for r in readings),
        )

    def count_readings(self, sensor_id: str | None = None) -> int:
        if sensor_id is None:
            row = self._con.execute("SELECT COUNT(*) FROM readings").fetchone()
        else:
            row = self._con.execute(
                "SELECT COUNT(*) FROM readings WHERE sensor_id = ?", (sensor_id,)
            ).fetchone()
        return int(row[0])

    def hourly_usage(self, sensor_id: str, start: datetime, end: datetime) -> list[HourlyUsage]:
        start = start.astimezone(TZ)
        end = end.astimezone(TZ)
        sums: dict[str, float] = dict(
            self._con.execute(
                "SELECT substr(ts, 1, 13) AS hour, SUM(value) FROM readings"
                " WHERE sensor_id = ? AND ts >= ? AND ts < ? GROUP BY hour ORDER BY hour",
                (sensor_id, start.isoformat(), end.isoformat()),
            ).fetchall()
        )
        h = start.replace(minute=0, second=0, microsecond=0)
        if h < start:
            h += _HOUR
        out: list[HourlyUsage] = []
        while h < end:
            out.append(HourlyUsage(sensor_id, h, float(sums.get(h.isoformat()[:13], 0.0))))
            h += _HOUR
        return out

    def insert_anomalies(self, anomalies: Iterable[Anomaly]) -> int:
        return self._insert(
            "INSERT OR IGNORE INTO anomalies(sensor_id, window_start, window_end, score, expected,"
            " actual, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (a.sensor_id, _iso(a.window_start), _iso(a.window_end), a.score, a.expected,
                 a.actual, a.reason)
                for a in anomalies
            ),
        )

    def list_anomalies(self, sensor_id: str) -> list[Anomaly]:
        rows = self._con.execute(
            "SELECT sensor_id, window_start, window_end, score, expected, actual, reason"
            " FROM anomalies WHERE sensor_id = ? ORDER BY window_start",
            (sensor_id,),
        ).fetchall()
        return [
            Anomaly(s, _parse(ws), _parse(we), sc, ex, ac, rs)
            for s, ws, we, sc, ex, ac, rs in rows
        ]

    def sensor_ids(self) -> list[str]:
        rows = self._con.execute("SELECT DISTINCT sensor_id FROM readings ORDER BY sensor_id")
        return [r[0] for r in rows.fetchall()]

    def log_alert(self, payload: AlertPayload, anomalies: Iterable[Anomaly]) -> str:
        alert_id = str(uuid.uuid4())
        extra = {"household_id": payload.household_id, "status": payload.status,
                 "details": payload.details}
        with self._con:
            self._con.execute(
                f"INSERT INTO alerts_log({_ALERT_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
                (alert_id, payload.kind, _iso(payload.window_start), _iso(payload.window_end),
                 payload.sentence, json.dumps(extra, ensure_ascii=False), _now()),
            )
            self._con.executemany(
                "INSERT OR IGNORE INTO alert_anomalies(alert_id, sensor_id, window_start,"
                " window_end, score, expected, actual, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (alert_id, a.sensor_id, _iso(a.window_start), _iso(a.window_end), a.score,
                     a.expected, a.actual, a.reason)
                    for a in anomalies
                ),
            )
        return alert_id

    def mark_sent(self, alert_id: str, remote_id: str) -> None:
        with self._con:
            self._con.execute(
                "UPDATE alerts_log SET sent_at = ?, remote_id = ? WHERE id = ?",
                (_now(), remote_id, alert_id),
            )

    def unsent_alerts(self) -> list[LoggedAlert]:
        rows = self._con.execute(
            f"SELECT {_ALERT_COLS} FROM alerts_log WHERE sent_at IS NULL ORDER BY created_at, rowid"
        ).fetchall()
        return [_logged_alert(r) for r in rows]

    def list_alert_log(self) -> list[LoggedAlert]:
        rows = self._con.execute(
            f"SELECT {_ALERT_COLS} FROM alerts_log ORDER BY created_at, rowid"
        ).fetchall()
        return [_logged_alert(r) for r in rows]

    def anomalies_for_alert(self, alert_id: str) -> list[Anomaly]:
        rows = self._con.execute(
            "SELECT sensor_id, window_start, window_end, score, expected, actual, reason"
            " FROM alert_anomalies WHERE alert_id = ? ORDER BY rowid",
            (alert_id,),
        ).fetchall()
        return [
            Anomaly(s, _parse(ws), _parse(we), sc, ex, ac, rs)
            for s, ws, we, sc, ex, ac, rs in rows
        ]

    def upsert_feedback(self, rows: Iterable[FeedbackRow]) -> int:
        # A changed verdict clears applied_at so the policy sees the new answer.
        return self._insert(
            f"INSERT INTO feedback({_FEEDBACK_COLS}) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET alert_id = excluded.alert_id,"
            " verdict = excluded.verdict, day = excluded.day, note = excluded.note,"
            " created_at = excluded.created_at,"
            " applied_at = CASE WHEN verdict = excluded.verdict THEN applied_at END"
            " WHERE alert_id IS NOT excluded.alert_id OR verdict IS NOT excluded.verdict"
            " OR day IS NOT excluded.day OR note IS NOT excluded.note"
            " OR created_at IS NOT excluded.created_at",
            (
                (f.id, f.alert_id, f.verdict, f.day.isoformat() if f.day else None, f.note,
                 _iso(f.created_at))
                for f in rows
            ),
        )

    def unapplied_feedback(self) -> list[FeedbackRow]:
        rows = self._con.execute(
            f"SELECT {_FEEDBACK_COLS} FROM feedback WHERE applied_at IS NULL"
            " ORDER BY created_at, rowid"
        ).fetchall()
        return [_feedback(r) for r in rows]

    def mark_applied(self, feedback_id: str) -> None:
        with self._con:
            self._con.execute(
                "UPDATE feedback SET applied_at = ? WHERE id = ?", (_now(), feedback_id)
            )

    def list_feedback(self) -> list[FeedbackRow]:
        rows = self._con.execute(
            f"SELECT {_FEEDBACK_COLS} FROM feedback ORDER BY created_at, rowid"
        ).fetchall()
        return [_feedback(r) for r in rows]

    def replace_away(self, periods: Iterable[AwayPeriod]) -> None:
        with self._con:
            self._con.execute("DELETE FROM away_periods")
            self._con.executemany(
                "INSERT OR REPLACE INTO away_periods(id, start_date, end_date, note)"
                " VALUES (?, ?, ?, ?)",
                (
                    (p.id or f"{p.start_date.isoformat()}/{p.end_date.isoformat()}",
                     p.start_date.isoformat(), p.end_date.isoformat(), p.note)
                    for p in periods
                ),
            )

    def list_away(self) -> list[AwayPeriod]:
        rows = self._con.execute(
            "SELECT id, start_date, end_date, note FROM away_periods ORDER BY start_date, id"
        ).fetchall()
        return [
            AwayPeriod(date.fromisoformat(s), date.fromisoformat(e), note, pid)
            for pid, s, e, note in rows
        ]

    def get_cursor(self, name: str) -> str | None:
        row = self._con.execute("SELECT value FROM cursors WHERE name = ?", (name,)).fetchone()
        return None if row is None else str(row[0])

    def set_cursor(self, name: str, value: str) -> None:
        with self._con:
            self._con.execute(
                "INSERT INTO cursors(name, value) VALUES (?, ?)"
                " ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (name, value),
            )

    def close(self) -> None:
        self._con.close()
