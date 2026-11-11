from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from solowatch.contracts import TZ
from solowatch.contracts_demo import DEMO_MAX_DAYS, RECENT_SLOTS
from solowatch.contracts_mvp import SupabaseConfig
from solowatch.virtual_home import RecordingSupabaseSink, VirtualClock, VirtualHome

SENSORS = ("water_main", "plug_fridge", "plug_tv", "plug_light")


@pytest.fixture
def home(tmp_path: Path) -> Iterator[VirtualHome]:
    h = VirtualHome(None, store_dir=tmp_path, sync_interval_s=0)
    h.reset()
    yield h
    h.close()


def _alert_log(h: VirtualHome) -> list[Any]:
    assert h._store is not None
    return h._run(h._store.list_alert_log)


def test_virtual_clock_advances_whole_days() -> None:
    c = VirtualClock(datetime(2026, 11, 2, tzinfo=TZ))
    c.advance_days(2)
    assert c.now() == datetime(2026, 11, 4, tzinfo=TZ)


def test_reset_loads_history_and_sends_past_alerts(home: VirtualHome) -> None:
    s = home.state()
    assert s.ready is True and s.error is None
    assert s.readings_total == 32256
    assert s.day_index == 0
    assert s.virtual_now == "2026-11-02T00:00:00+09:00"
    anomalies = [la for la in _alert_log(home) if la.payload.kind == "anomaly"]
    assert len(anomalies) >= 7
    # 10-26·27 away seed: nothing is flagged while the house is empty
    away_days = {date(2026, 10, 26), date(2026, 10, 27)}
    assert not [la for la in anomalies if la.payload.window_start.astimezone(TZ).date() in away_days]
    assert set(s.recent) == set(SENSORS)
    for rows in s.recent.values():
        assert len(rows) == RECENT_SLOTS
        assert rows[0][0] < rows[-1][0]
        assert rows[-1][0] == "2026-11-01T23:55:00+09:00"


def test_inject_no_morning_water_alerts_and_scores(home: VirtualHome) -> None:
    r = home.inject("no_morning_water")
    assert r.readings == 1152
    assert r.day == "2026-11-02" and r.day_type == "weekday"
    assert any("아침 (6~12시) 물 사용 없음" in a["sentence"] for a in r.alerts)
    assert all(a["window_start"].startswith("2026-11-02") and a["remote_id"] for a in r.alerts)
    assert len(r.scores) == 16
    focus = next(s for s in r.scores if (s.sensor_id, s.window) == ("water_main", "morning"))
    assert focus.flagged is True and focus.score >= 0.995
    assert focus.actual == 0.0 and focus.expected > 5.0
    assert r.previous_scores == [] and r.auto_reset is False and r.daily_sent is True
    s = home.state()
    assert s.day_index == 1 and s.readings_total == 32256 + 1152
    assert s.virtual_now == "2026-11-03T00:00:00+09:00"
    assert s.history == [{"day": "2026-11-02", "kind": "no_morning_water", "alerts": len(r.alerts)}]
    assert s.last_inject == r
    assert s.recent["water_main"][-1][0] == "2026-11-02T23:55:00+09:00"


def test_second_same_kind_carries_previous_scores(home: VirtualHome) -> None:
    first = home.inject("no_morning_water")
    home.inject("normal")
    second = home.inject("no_morning_water")
    assert second.previous_scores == first.scores
    assert second.day == "2026-11-04"


def test_normal_day_has_no_alerts(home: VirtualHome) -> None:
    r = home.inject("normal")
    assert r.alerts == []
    assert not any(s.flagged for s in r.scores)


def test_unknown_kind_raises(home: VirtualHome) -> None:
    with pytest.raises(ValueError):
        home.inject("flood")  # type: ignore[arg-type]
    assert home.state().day_index == 0


def test_auto_reset_after_max_days(home: VirtualHome) -> None:
    for _ in range(DEMO_MAX_DAYS):
        assert home.inject("normal").auto_reset is False
    assert home.state().day_index == DEMO_MAX_DAYS
    r = home.inject("normal")
    assert r.auto_reset is True and r.day == "2026-11-02"
    s = home.state()
    assert s.day_index == 1 and len(s.history) == 1
    assert s.readings_total == 32256 + 1152


def test_concurrent_state_calls(home: VirtualHome) -> None:
    errors: list[BaseException] = []
    results: list[int] = []

    def worker() -> None:
        try:
            for _ in range(5):
                results.append(home.state().readings_total)
        except BaseException as e:  # noqa: BLE001 - collected for the assertion below
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    home.inject("normal")
    for t in threads:
        t.join()
    assert errors == []
    assert len(results) == 15


class _FakeRemote:
    """Stands in for Supabase behind RecordingSupabaseSink._execute (no network)."""

    def __init__(self) -> None:
        self.n = 0
        self.alerts: list[str] = []
        self.feedback: list[dict[str, Any]] = []

    def execute(self, what: str) -> list[dict[str, Any]]:
        self.n += 1
        if what == "insert alerts":
            rid = f"00000000-0000-4000-8000-{self.n:012d}"
            self.alerts.append(rid)
            return [{"id": rid}]
        if what == "upsert daily_reports":
            return [{"id": f"daily-{self.n}"}]
        if what == "select alert_feedback":
            rows, self.feedback = self.feedback, []
            return rows
        if what == "select away_periods":
            return [{"id": "away-1", "start_date": "2026-10-26", "end_date": "2026-10-27",
                     "note": "demo-seed"}]
        raise AssertionError(what)


def test_feedback_lowers_score_and_fills_outbox(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    remote = _FakeRemote()
    monkeypatch.setattr(RecordingSupabaseSink, "_execute",
                        lambda self, what, build: remote.execute(what))
    monkeypatch.setattr(VirtualHome, "_reset_remote", lambda self: None)
    h = VirtualHome(SupabaseConfig("http://localhost:1", "anon", "d@example.com", "pw"),
                    store_dir=tmp_path, sync_interval_s=0)
    try:
        s = h.reset()
        tables = [o.table for o in s.outbox]
        assert "alerts" in tables and "daily_reports" in tables
        assert [o.summary for o in s.outbox if o.table == "away_periods"] == ["외출 10-26 ~ 10-27"]
        assert all(o.direction == "out" for o in s.outbox if o.table in ("alerts", "daily_reports"))

        first = h.inject("no_morning_water")
        alert = next(a for a in first.alerts if "아침" in a["sentence"])
        remote.feedback = [{"id": "fb-1", "alert_id": alert["remote_id"], "verdict": "ok",
                            "day": None, "note": "", "created_at": "2026-11-03T09:00:00+09:00"}]
        assert h.sync() == 1
        fb = [o for o in h.state().outbox if o.table == "alert_feedback"]
        assert len(fb) == 1 and fb[0].direction == "in"
        assert fb[0].summary.startswith("괜찮았음 · 아침 (6~12시) 창 평소 ")
        assert fb[0].summary.endswith(" L") and fb[0].row["id"] == "fb-1"

        second = h.inject("no_morning_water")
        key = ("water_main", "morning")
        before = next(x for x in second.previous_scores if (x.sensor_id, x.window) == key)
        after = next(x for x in second.scores if (x.sensor_id, x.window) == key)
        assert after.expected < before.expected
        assert after.score <= before.score
        assert len(h.state().outbox) <= 50
    finally:
        h.close()
