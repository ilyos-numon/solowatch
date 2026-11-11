from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from solowatch import daemon
from solowatch.contracts import TZ, Reading
from solowatch.contracts_mvp import (
    DEFAULT_HOME,
    DEFAULT_SENSORS,
    DEMO_HOUSEHOLD_ID,
    AlertPayload,
    AppConfig,
    AwayPeriod,
    DailyReportPayload,
    DetectorConfig,
    FeedbackRow,
    MqttConfig,
    SupabaseConfig,
)
from solowatch.daemon import Daemon
from solowatch.policy import HomePolicy
from solowatch.simulate_home import simulate_home
from solowatch.sinks import AppriseSink, SinkError, SupabaseSink
from solowatch.store import SqliteStore

START = date(2026, 10, 5)  # Monday
WATER = DEFAULT_SENSORS[0]
NOW = datetime(2026, 10, 20, 0, 0, tzinfo=TZ)  # day 15 00:00 -> windows through 10-19 closed
EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "solowatch.example.toml"


class FakeSupabase(SupabaseSink):
    def __init__(self) -> None:
        super().__init__(SupabaseConfig("http://localhost:1", "anon", "d@example.com", "pw"))
        self.alerts: list[AlertPayload] = []
        self.daily: list[DailyReportPayload] = []
        self.feedback: list[FeedbackRow] = []
        self.away: list[AwayPeriod] = []
        self.fail_alerts = 0
        self.since: list[datetime | None] = []

    def send_alert(self, p: AlertPayload) -> str:
        if self.fail_alerts:
            self.fail_alerts -= 1
            raise SinkError("supabase down")
        self.alerts.append(p)
        return f"remote-{len(self.alerts)}"

    def send_daily(self, p: DailyReportPayload) -> str:
        self.daily.append(p)
        return f"daily-{len(self.daily)}"

    def fetch_feedback(self, household_id: str, since: datetime | None) -> list[FeedbackRow]:
        self.since.append(since)
        return [f for f in self.feedback if since is None or f.created_at > since]

    def fetch_away(self, household_id: str) -> list[AwayPeriod]:
        return list(self.away)


def _cfg(sensors: tuple = (WATER,), install_start: date | None = START,
         daily_hour: int = 20) -> AppConfig:
    return AppConfig(
        household_id=DEMO_HOUSEHOLD_ID, slug="home-demo", name="demo",
        mqtt=MqttConfig("localhost", 57884), store_path=":memory:",
        detector=DetectorConfig(learn_days=14, threshold=0.995, tick_seconds=60,
                                daily_report_hour=daily_hour),
        supabase=None, apprise_urls=(), sensors=sensors, install_start=install_start,
    )


def _water_store(skip_day: int = 14, days: int = 15) -> SqliteStore:
    """25 L every morning at 07:00 except `skip_day` (10-19, a Monday)."""
    store = SqliteStore(":memory:")
    base = datetime.combine(START, datetime.min.time(), TZ)
    store.insert_readings(
        Reading("water_main", base + timedelta(days=d, hours=7), 24.0 + d % 3)
        for d in range(days) if d != skip_day
    )
    return store


def _daemon(store: SqliteStore, supabase: SupabaseSink | None = None, now: datetime = NOW,
            cfg: AppConfig | None = None) -> Daemon:
    cfg = cfg or _cfg()
    learn_until = datetime.combine(START, datetime.min.time(), TZ) + timedelta(days=14)
    policy = HomePolicy(cfg.sensors, learn_until, cfg.detector.threshold)
    return Daemon(cfg, store, policy, None, supabase, AppriseSink([]), lambda: now)


def test_tick_advances_cursor_and_logs_one_alert() -> None:
    store = _water_store()
    d = _daemon(store)
    result = d.tick()
    assert result.alerts == 1
    assert store.get_cursor("hour:water_main") == NOW.isoformat()
    log = store.list_alert_log()
    assert len(log) == 1
    assert log[0].payload.window_start == datetime(2026, 10, 19, 6, tzinfo=TZ)
    assert "물 사용 없음" in log[0].payload.sentence
    assert len(store.anomalies_for_alert(log[0].id)) == 1
    # no Supabase: delivered locally, remote_id is the local id
    assert log[0].sent_at is not None and log[0].remote_id == log[0].id
    # same clock again: nothing new
    again = d.tick()
    assert again.alerts == 0
    assert len(store.list_alert_log()) == 1


def test_failed_sink_keeps_alert_unsent_until_next_tick() -> None:
    store = _water_store()
    sb = FakeSupabase()
    sb.fail_alerts = 1
    d = _daemon(store, sb)
    assert d.tick().alerts == 1
    unsent = store.unsent_alerts()
    assert len(unsent) == 1 and unsent[0].sent_at is None
    assert sb.alerts == []
    d.tick()
    assert store.unsent_alerts() == []
    assert [a.remote_id for a in store.list_alert_log()] == ["remote-1"]
    assert len(sb.alerts) == 1


def test_feedback_ok_lowers_learned_mean_and_marks_applied() -> None:
    store = _water_store()
    sb = FakeSupabase()
    d = _daemon(store, sb)
    d.tick()
    policy = d.policy
    before = policy.learned_mean("water_main", "weekday", "morning")
    created = datetime(2026, 10, 20, 0, 5, tzinfo=TZ)
    sb.feedback.append(FeedbackRow("fb-1", "remote-1", "ok", None, "", created))
    result = d.tick()
    assert result.feedback_applied == 1
    after = policy.learned_mean("water_main", "weekday", "morning")
    assert after < before
    assert store.unapplied_feedback() == []
    assert [f.id for f in store.list_feedback()] == ["fb-1"]
    assert store.get_cursor("feedback_since") == created.isoformat()
    assert sb.since[-1] is None
    assert d.feedback_log[0]["mean_before"] == pytest.approx(before)
    assert d.feedback_log[0]["mean_after"] == pytest.approx(after)
    d.tick()
    assert sb.since[-1] == created


def test_restart_rebuilds_policy_from_store() -> None:
    store = _water_store()
    sb = FakeSupabase()
    first = _daemon(store, sb)
    first.tick()
    sb.feedback.append(FeedbackRow("fb-1", "remote-1", "ok", None, "",
                                   datetime(2026, 10, 20, 0, 5, tzinfo=TZ)))
    first.tick()
    expected = first.policy.learned_mean("water_main", "weekday", "morning")
    second = _daemon(store, sb)
    assert second.policy.learned_mean("water_main", "weekday", "morning") == pytest.approx(expected)
    assert second.tick().alerts == 0


def test_away_periods_suppress_alerts_and_are_stored() -> None:
    store = _water_store()
    sb = FakeSupabase()
    sb.away.append(AwayPeriod(date(2026, 10, 19), date(2026, 10, 19), "외출", "away-1"))
    d = _daemon(store, sb)
    assert d.tick().alerts == 0
    assert [p.id for p in store.list_away()] == ["away-1"]


def test_daily_report_for_previous_day_sent_once() -> None:
    store = _water_store()
    sb = FakeSupabase()
    d = _daemon(store, sb)
    assert d.tick().daily_sent is True
    assert [p.day for p in sb.daily] == [date(2026, 10, 19)]
    assert "알림 1건" in sb.daily[0].sentence
    assert store.get_cursor("daily:2026-10-19") is not None
    assert d.tick().daily_sent is False
    assert len(sb.daily) == 1


def test_daily_report_today_after_report_hour() -> None:
    store = _water_store(days=16)
    sb = FakeSupabase()
    d = _daemon(store, sb, now=datetime(2026, 10, 20, 21, 0, tzinfo=TZ))
    assert d.tick().daily_sent is True
    assert [p.day for p in sb.daily] == [date(2026, 10, 20)]


def test_default_home_once_matches_e2e_expectation() -> None:
    store = SqliteStore(":memory:")
    for readings in simulate_home(DEFAULT_HOME).values():
        store.insert_readings(readings)
    sb = FakeSupabase()
    sb.away.extend(DEFAULT_HOME.away_periods())
    cfg = _cfg(sensors=DEFAULT_SENSORS)
    d = _daemon(store, sb, now=datetime(2026, 11, 2, 0, 0, tzinfo=TZ), cfg=cfg)
    d.tick()
    days = {a.payload.window_start.date() for a in store.list_alert_log()}
    assert {e.day for e in DEFAULT_HOME.events} <= days
    assert date(2026, 10, 26) not in days and date(2026, 10, 27) not in days
    assert [p.day for p in sb.daily] == [date(2026, 11, 1)]


def test_learn_until_uses_install_start_then_first_reading() -> None:
    store = _water_store()
    assert daemon.learn_until(_cfg(), store) == datetime(2026, 10, 19, tzinfo=TZ)
    later = _cfg(install_start=date(2026, 10, 10))
    assert daemon.learn_until(later, store) == datetime(2026, 10, 24, tzinfo=TZ)
    assert daemon.learn_until(_cfg(install_start=None), store) == datetime(2026, 10, 19, tzinfo=TZ)


def test_main_missing_env_exits_2(monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SOLOWATCH_DEVICE_EMAIL",
                 "SOLOWATCH_DEVICE_PASSWORD", "SOLOWATCH_APPRISE_URLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPABASE_URL", "http://localhost:57321")
    assert daemon.main(["--config", str(EXAMPLE), "--once"]) == 2
    assert "SUPABASE_ANON_KEY" in capsys.readouterr().err


def _local_config(tmp_path: Path, port: int) -> Path:
    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace("port = 57883", f"port = {port}")
    text = text.replace('path = "data/raw/home.sqlite"', f'path = "{tmp_path / "home.sqlite"}"')
    head, _, rest = text.partition("[supabase]")
    _, _, tail = rest.partition("[apprise]")
    cfg = tmp_path / "c.toml"
    cfg.write_text(head + "[apprise]" + tail, encoding="utf-8")
    return cfg


def test_main_broker_down_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("SOLOWATCH_APPRISE_URLS", "")
    cfg = _local_config(tmp_path, 57884)
    code = daemon.main(["--config", str(cfg), "--once", "--now", "2026-11-02T00:00:00+09:00",
                        "--connect-timeout", "2"])
    assert code == 3
    assert "broker" in capsys.readouterr().err


def test_main_bad_now_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOWATCH_APPRISE_URLS", "")
    cfg = _local_config(tmp_path, 57884)
    assert daemon.main(["--config", str(cfg), "--once", "--now", "yesterday"]) == 2


def test_run_once_without_ingester_ticks_and_prints_stats(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = _water_store()
    sb = FakeSupabase()
    d = _daemon(store, sb)
    sb.feedback.append(FeedbackRow("fb-0", "unknown", "ok", None, "",
                                   datetime(2026, 10, 19, tzinfo=TZ)))
    assert d.run(once=True, idle_seconds=0) == 0
    out = capsys.readouterr().out
    assert "alerts=1" in out and "dropped=0" in out
    path = tmp_path / "o.json"
    d.write_json(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mean_before"] is None and data["mean_after"] is None
    assert data["tick"]["alerts"] == 1
