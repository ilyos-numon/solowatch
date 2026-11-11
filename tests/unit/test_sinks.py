from __future__ import annotations

import json
import logging
import socket
import threading
from collections.abc import Iterator
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from solowatch import sinks
from solowatch.contracts import TZ
from solowatch.contracts_mvp import (
    DEMO_HOUSEHOLD_ID,
    AlertPayload,
    AwayPeriod,
    DailyReportPayload,
    FeedbackRow,
    SupabaseConfig,
)
from solowatch.sinks import AppriseSink, SinkError, SupabaseSink, deliver

SENTENCE = "이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다"
SINK_PORT = 8842


def _alert() -> AlertPayload:
    return AlertPayload(DEMO_HOUSEHOLD_ID, "anomaly", datetime(2026, 10, 30, 6, tzinfo=TZ),
                        datetime(2026, 10, 30, 12, tzinfo=TZ), SENTENCE,
                        {"sensors": [{"sensor_id": "water_main", "reason": "r",
                                      "expected": 25.0, "actual": 0.0}]})


def _daily() -> DailyReportPayload:
    return DailyReportPayload(DEMO_HOUSEHOLD_ID, date(2026, 10, 30), "오늘 리듬 정상",
                              {"water_main": [False] * 24}, {})


# ---------- Apprise (local http.server) ----------

class _Recorder(BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        _Recorder.received.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def json_server() -> Iterator[list[dict[str, Any]]]:
    _Recorder.received = []
    server = HTTPServer(("localhost", SINK_PORT), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Recorder.received
    finally:
        server.shutdown()
        server.server_close()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return int(s.getsockname()[1])


def test_apprise_json_sink_receives_sentence(json_server: list[dict[str, Any]]) -> None:
    assert AppriseSink([f"json://localhost:{SINK_PORT}/"]).send(SENTENCE) is True
    assert len(json_server) == 1
    assert json_server[0]["message"] == SENTENCE
    assert json_server[0]["title"] == "홀로안심"


def test_apprise_empty_urls_is_noop() -> None:
    assert AppriseSink([]).send(SENTENCE) is True
    assert AppriseSink(["", "  "]).send(SENTENCE) is True


def test_apprise_closed_port_returns_false(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="solowatch.sinks"):
        assert AppriseSink([f"json://localhost:{_closed_port()}/"]).send(SENTENCE) is False
    assert any(r.name == "solowatch.sinks" for r in caplog.records)


# ---------- deliver ----------

class FakeSupabaseSink:
    def __init__(self, fail: bool = False) -> None:
        self.alerts: list[AlertPayload] = []
        self.dailies: list[DailyReportPayload] = []
        self.fail = fail

    def send_alert(self, p: AlertPayload) -> str:
        if self.fail:
            raise SinkError("down")
        self.alerts.append(p)
        return f"alert-{len(self.alerts)}"

    def send_daily(self, p: DailyReportPayload) -> str:
        self.dailies.append(p)
        return "daily-1"


def test_deliver_apprise_down_still_returns_supabase_id(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeSupabaseSink()
    with caplog.at_level(logging.WARNING, logger="solowatch.sinks"):
        rid = deliver(_alert(), fake,  # type: ignore[arg-type]
                      AppriseSink([f"json://localhost:{_closed_port()}/"]))
    assert rid == "alert-1"
    assert len(fake.alerts) == 1
    warnings = [r for r in caplog.records if r.name == "solowatch.sinks"
                and r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_deliver_order_supabase_then_apprise(json_server: list[dict[str, Any]]) -> None:
    fake = FakeSupabaseSink()
    rid = deliver(_daily(), fake, AppriseSink([f"json://localhost:{SINK_PORT}/"]))  # type: ignore[arg-type]
    assert rid == "daily-1"
    assert len(fake.dailies) == 1
    assert json_server[0]["message"] == "오늘 리듬 정상"


def test_deliver_without_supabase_returns_none() -> None:
    assert deliver(_alert(), None, AppriseSink([])) is None


def test_deliver_supabase_failure_raises_and_skips_apprise(
        json_server: list[dict[str, Any]]) -> None:
    with pytest.raises(SinkError):
        deliver(_alert(), FakeSupabaseSink(fail=True),  # type: ignore[arg-type]
                AppriseSink([f"json://localhost:{SINK_PORT}/"]))
    assert json_server == []


# ---------- SupabaseSink with a fake supabase-py client ----------

class _Resp:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, client: FakeClient, table: str) -> None:
        self.client, self.table, self.calls = client, table, []  # type: list[tuple[Any, ...]]
        client.queries.append(self)

    def _chain(self, *call: Any) -> _Query:
        self.calls.append(call)
        return self

    def insert(self, row: dict[str, Any]) -> _Query:
        return self._chain("insert", row)

    def upsert(self, row: dict[str, Any], on_conflict: str = "") -> _Query:
        return self._chain("upsert", row, on_conflict)

    def select(self, *cols: str) -> _Query:
        return self._chain("select", *cols)

    def eq(self, col: str, val: Any) -> _Query:
        return self._chain("eq", col, val)

    def gt(self, col: str, val: Any) -> _Query:
        return self._chain("gt", col, val)

    def order(self, col: str, desc: bool = False) -> _Query:
        return self._chain("order", col, desc)

    def execute(self) -> _Resp:
        if self.client.fail_execute:
            raise RuntimeError("postgrest down")
        op = self.calls[0][0]
        if op in ("insert", "upsert"):
            return _Resp([{**self.calls[0][1], "id": "remote-1"}])
        return _Resp(self.client.rows.get(self.table, []))


class _Auth:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def sign_in_with_password(self, creds: dict[str, str]) -> None:
        self.client.logins.append(creds)
        if self.client.fail_login:
            raise RuntimeError("bad credentials")


class FakeClient:
    def __init__(self) -> None:
        self.queries: list[_Query] = []
        self.logins: list[dict[str, str]] = []
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.fail_login = False
        self.fail_execute = False
        self.auth = _Auth(self)

    def table(self, name: str) -> _Query:
        return _Query(self, name)


CFG = SupabaseConfig("http://localhost:57321", "anon", "device@example.com", "pw")


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient()
    created: list[tuple[str, str]] = []

    def _create(url: str, key: str) -> FakeClient:
        created.append((url, key))
        return client

    monkeypatch.setattr(sinks, "create_client", _create)
    client.created = created  # type: ignore[attr-defined]
    return client


def test_supabase_login_is_lazy_and_once(fake_client: FakeClient) -> None:
    sink = SupabaseSink(CFG)
    assert fake_client.logins == []
    assert sink.send_alert(_alert()) == "remote-1"
    assert sink.send_alert(_alert()) == "remote-1"
    assert fake_client.logins == [{"email": "device@example.com", "password": "pw"}]
    assert fake_client.created == [("http://localhost:57321", "anon")]  # type: ignore[attr-defined]


def test_send_alert_inserts_to_row(fake_client: FakeClient) -> None:
    SupabaseSink(CFG).send_alert(_alert())
    q = fake_client.queries[-1]
    assert q.table == "alerts"
    assert q.calls[0] == ("insert", _alert().to_row())


def test_send_daily_upserts_on_household_day(fake_client: FakeClient) -> None:
    assert SupabaseSink(CFG).send_daily(_daily()) == "remote-1"
    q = fake_client.queries[-1]
    assert q.table == "daily_reports"
    assert q.calls[0] == ("upsert", _daily().to_row(), "household_id,day")


def test_fetch_feedback_maps_rows(fake_client: FakeClient) -> None:
    fake_client.rows["alert_feedback"] = [
        {"id": "f1", "alert_id": "a1", "household_id": DEMO_HOUSEHOLD_ID, "user_id": "u",
         "verdict": "ok", "day": None, "note": None, "created_at": "2026-10-30T10:00:00+00:00"},
        {"id": "f2", "alert_id": None, "household_id": DEMO_HOUSEHOLD_ID, "user_id": "u",
         "verdict": "missed", "day": "2026-10-29", "note": "x",
         "created_at": "2026-10-30T11:00:00Z"},
    ]
    since = datetime(2026, 10, 30, 9, tzinfo=TZ)
    rows = SupabaseSink(CFG).fetch_feedback(DEMO_HOUSEHOLD_ID, since)
    assert rows[0] == FeedbackRow("f1", "a1", "ok", None, "",
                                  datetime.fromisoformat("2026-10-30T10:00:00+00:00"))
    assert rows[1].day == date(2026, 10, 29)
    assert rows[1].created_at.tzinfo is not None
    q = fake_client.queries[-1]
    assert q.table == "alert_feedback"
    assert ("eq", "household_id", DEMO_HOUSEHOLD_ID) in q.calls
    assert ("gt", "created_at", since.isoformat()) in q.calls
    assert ("order", "created_at", False) in q.calls


def test_fetch_feedback_without_since_has_no_gt(fake_client: FakeClient) -> None:
    SupabaseSink(CFG).fetch_feedback(DEMO_HOUSEHOLD_ID, None)
    assert not any(c[0] == "gt" for c in fake_client.queries[-1].calls)


def test_fetch_away_maps_rows(fake_client: FakeClient) -> None:
    fake_client.rows["away_periods"] = [
        {"id": "w1", "household_id": DEMO_HOUSEHOLD_ID, "start_date": "2026-10-26",
         "end_date": "2026-10-27", "note": None, "created_by": "u"},
    ]
    assert SupabaseSink(CFG).fetch_away(DEMO_HOUSEHOLD_ID) == [
        AwayPeriod(date(2026, 10, 26), date(2026, 10, 27), "", "w1")]


def test_login_failure_raises_sink_error_and_retries_next_time(fake_client: FakeClient) -> None:
    fake_client.fail_login = True
    sink = SupabaseSink(CFG)
    with pytest.raises(SinkError):
        sink.send_alert(_alert())
    fake_client.fail_login = False
    assert sink.send_alert(_alert()) == "remote-1"
    assert len(fake_client.logins) == 2


def test_execute_failure_raises_sink_error(fake_client: FakeClient) -> None:
    fake_client.fail_execute = True
    sink = SupabaseSink(CFG)
    for call in (lambda: sink.send_alert(_alert()), lambda: sink.send_daily(_daily()),
                 lambda: sink.fetch_feedback(DEMO_HOUSEHOLD_ID, None),
                 lambda: sink.fetch_away(DEMO_HOUSEHOLD_ID)):
        with pytest.raises(SinkError):
            call()
