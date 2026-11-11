"""Home chain: mock sensors -> MQTT -> daemon -> detect -> alert -> Supabase -> family app -> feedback."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import paho.mqtt.client as mqtt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import (
    BROKER_PORT,
    DEAD_PORT,
    ROOT,
    Broker,
    admin_client,
    clean_supabase,
    cli,
    db_of,
    family_client,
    port_open,
    seed_away,
    start_daemon,
    wait_for,
    write_config,
)
from paho.mqtt.enums import CallbackAPIVersion

from solowatch.contracts import TZ

NOW = "2026-11-02T00:00:00+09:00"
NOW_FEEDBACK = "2026-11-02T00:10:00+09:00"
APPRISE_PORT = 8842
EXPECTED_DAYS = {"2026-10-21", "2026-10-23", "2026-10-25", "2026-10-28",
                 "2026-10-29", "2026-10-30", "2026-10-31"}
QUIET_DAYS = ("2026-10-26", "2026-10-27")
SENTENCE_1030 = "이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다"
IDLE = "8"   # publish-mock needs a few seconds (uv start, simulation) before its first message


def shot_dir() -> str:
    return os.environ.get("ILLY_SHOT_DIR", "tests/e2e/screenshots")


@dataclass
class Chain:
    cfg: Path
    db: Path
    pub: subprocess.CompletedProcess[str]
    daemon_code: int
    daemon_out: str
    daemon_err: str


def run_chain(directory: Path, broker: Broker, env: dict[str, str], supabase: bool,
              name: str = "chain.toml") -> Chain:
    """Daemon first (it must be subscribed: clean session), then publish-mock, then wait."""
    cfg = write_config(directory, name, supabase=supabase)
    if supabase:
        clean_supabase()
        seed_away("2026-10-26", "2026-10-27")
    offset = broker.offset()
    daemon = start_daemon("--config", str(cfg), "--once", "--now", NOW, "--idle-seconds", IDLE,
                          env=env)
    try:
        assert wait_for(lambda: broker.subscribed(offset), 60), "daemon never subscribed"
        pub = cli("publish-mock", "--config", str(cfg), env=env, timeout=300)
        out, err = daemon.communicate(timeout=240)
    finally:
        if daemon.poll() is None:
            daemon.kill()
    return Chain(cfg, db_of(cfg), pub, daemon.returncode, out, err)


def query(db: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    con = sqlite3.connect(db)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


class _Sink(BaseHTTPRequestHandler):
    bodies: ClassVar[list[str]] = []

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0))
        _Sink.bodies.append(self.rfile.read(n).decode("utf-8", "replace"))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture(scope="module")
def apprise_sink() -> Any:
    _Sink.bodies = []
    srv = HTTPServer(("localhost", APPRISE_PORT), _Sink)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield _Sink
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def chain(broker: Broker, apprise_sink: Any, e2e_env: dict[str, str], tmp_path: Path) -> Any:
    """A full replay into a fresh store and a cleaned Supabase household (about 12 s)."""
    clean_supabase()
    apprise_sink.bodies.clear()
    env = dict(e2e_env, SOLOWATCH_APPRISE_URLS=f"json://localhost:{APPRISE_PORT}")
    try:
        yield run_chain(tmp_path / "chain", broker, env, supabase=True)
    finally:
        clean_supabase()


def test_publish_and_daemon_once(chain: Chain) -> None:
    assert chain.pub.returncode == 0, chain.pub.stderr
    assert "PUBLISHED 32256 messages for 4 sensors" in chain.pub.stdout
    assert chain.daemon_code == 0, chain.daemon_err[-2000:]

    assert query(chain.db, "select count(*) from readings")[0][0] == 32256
    days = {r[0] for r in query(
        chain.db, "select substr(window_start,1,10) from alerts_log where kind='anomaly'")}
    n_alerts = query(chain.db, "select count(*) from alerts_log where kind='anomaly'")[0][0]
    assert n_alerts >= 7, days
    assert EXPECTED_DAYS <= days, days
    for quiet in QUIET_DAYS:
        assert quiet not in days
    assert query(chain.db, "select count(*) from alerts_log where kind='anomaly' "
                           "and sent_at is null")[0][0] == 0

    # What the family sees through RLS.
    family = family_client()
    rows = family.table("alerts").select("sentence,window_start").eq("kind", "anomaly").execute().data
    assert len(rows) >= 7
    on_1030 = [r["sentence"] for r in rows
               if datetime.fromisoformat(r["window_start"]).astimezone(TZ).date().isoformat()
               == "2026-10-30"]
    assert SENTENCE_1030 in on_1030, on_1030
    daily = family.table("daily_reports").select("day").eq("day", "2026-11-01").execute().data
    assert len(daily) == 1


def test_apprise_mirror(chain: Chain, apprise_sink: Any) -> None:
    assert chain.daemon_code == 0
    messages = [json.loads(b)["message"] for b in apprise_sink.bodies]
    assert SENTENCE_1030 in messages, messages


def test_malformed_dropped(broker: Broker, e2e_env: dict[str, str], make_config: Any) -> None:
    cfg = make_config("malformed.toml", supabase=False)
    offset = broker.offset()
    daemon = start_daemon("--config", str(cfg), "--once", "--now", NOW, "--idle-seconds", "3",
                          env=e2e_env)
    try:
        assert wait_for(lambda: broker.subscribed(offset), 60)
        c = mqtt.Client(CallbackAPIVersion.VERSION2)
        c.connect("localhost", BROKER_PORT)
        c.loop_start()
        info = c.publish("solowatch/home-demo/water_main/state", b"\xff\xfe{not json", qos=1)
        info.wait_for_publish(10)
        c.loop_stop()
        c.disconnect()
        out, err = daemon.communicate(timeout=60)
    finally:
        if daemon.poll() is None:
            daemon.kill()
    assert daemon.returncode == 0, err[-1500:]
    assert "dropped=1" in out, out
    assert "stored=0" in out, out


def test_broker_down_exit_3(make_config: Any, e2e_env: dict[str, str]) -> None:
    assert not port_open(DEAD_PORT)
    cfg = make_config("dead.toml", port=DEAD_PORT, supabase=False)
    t0 = time.monotonic()
    proc = subprocess.run(["uv", "run", "solowatch", "daemon", "--config", str(cfg), "--once"],
                          check=False, cwd=ROOT, text=True, capture_output=True, env=e2e_env, timeout=60)
    assert proc.returncode == 3, proc.stderr
    assert time.monotonic() - t0 < 20
    assert "broker unreachable" in proc.stderr


def test_missing_env_exit_2(make_config: Any, e2e_env: dict[str, str]) -> None:
    cfg = make_config("noenv.toml")
    env = {k: v for k, v in e2e_env.items() if not k.startswith("SUPABASE_")}
    proc = subprocess.run(["uv", "run", "solowatch", "daemon", "--config", str(cfg), "--once"],
                          check=False, cwd=ROOT, text=True, capture_output=True, env=env, timeout=60)
    assert proc.returncode == 2, proc.stderr
    assert "config error" in proc.stderr
    assert "SUPABASE_URL" in proc.stderr


def test_feedback_round_trip(chain: Chain, e2e_env: dict[str, str],
                             tmp_path: Path) -> None:
    assert chain.daemon_code == 0
    # Work on a copy so the shared chain store stays untouched.
    cfg = write_config(tmp_path, "feedback.toml", supabase=True)
    db = db_of(cfg)
    shutil.copy(chain.db, db)

    pw = subprocess.run(
        ["bash", "-c", ("source ~/.nvm/nvm.sh >/dev/null 2>&1; "
                        "cd web && npx playwright test --project=chain --workers=1")],
        check=False, cwd=ROOT, text=True, capture_output=True, timeout=240,
        env=dict(e2e_env, ILLY_SHOT_DIR=str(Path(shot_dir()).resolve())))
    assert pw.returncode == 0, pw.stdout[-3000:] + pw.stderr[-1500:]

    out_json = tmp_path / "feedback.json"
    try:
        proc = subprocess.run(
            ["uv", "run", "solowatch", "daemon", "--config", str(cfg), "--once",
             "--now", NOW_FEEDBACK, "--idle-seconds", "2", "--json-out", str(out_json)],
            check=False, cwd=ROOT, text=True, capture_output=True, env=e2e_env, timeout=120)
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert "feedback=1" in proc.stdout, proc.stdout

        rows = query(db, "select verdict, applied_at from feedback")
        assert rows and all(r[1] is not None for r in rows), rows
        assert [r[0] for r in rows] == ["ok"]
        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert data["mean_before"] is not None
        assert data["mean_before"] > data["mean_after"], data
        print(f"mean_before={data['mean_before']} mean_after={data['mean_after']}")
    finally:
        admin_client().table("alert_feedback").delete().eq(
            "household_id", "11111111-1111-4111-8111-111111111111").execute()


def test_two_runs_identical(chain: Chain, broker: Broker, e2e_env: dict[str, str],
                            tmp_path: Path) -> None:
    assert chain.daemon_code == 0
    env = dict(e2e_env, SOLOWATCH_APPRISE_URLS="")
    sql = "select window_start, sentence from alerts_log where kind='anomaly' order by window_start"
    first_rows = query(chain.db, sql)
    assert first_rows
    try:
        second = run_chain(tmp_path / "second", broker, env, supabase=True, name="second.toml")
        assert second.pub.returncode == 0, second.pub.stderr
        assert second.daemon_code == 0, second.daemon_err[-2000:]
        assert query(second.db, sql) == first_rows
    finally:
        clean_supabase()
    assert re.search(r"readings=\d+", second.daemon_out)
