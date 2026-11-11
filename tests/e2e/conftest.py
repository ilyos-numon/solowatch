"""Fixtures for the home-chain E2E: dev MQTT broker, temp config, Supabase cleanup, helpers."""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
BROKER_PORT = 57883
DEAD_PORT = 57884
DEMO_HID = "11111111-1111-4111-8111-111111111111"
PASSWORD = "solowatch-demo-1234"
FAMILY_EMAIL = "family@example.com"
MOSQUITTO = shutil.which("mosquitto") or "/opt/homebrew/sbin/mosquitto"
SENSOR_TOPICS = [f"solowatch/home-demo/{s}/state"
                 for s in ("water_main", "plug_fridge", "plug_tv", "plug_light")]


def _load_dotenv() -> None:
    """Fill missing env vars from .env (values are never printed)."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line.strip())
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")


_load_dotenv()


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("localhost", port)) == 0


def wait_for(cond: Callable[[], bool], timeout: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return cond()


# -- broker ------------------------------------------------------------------------------------

@dataclass
class Broker:
    log: Path

    def subscribed(self, since: int) -> bool:
        """True once all four sensor topics were subscribed after byte offset `since`."""
        text = self.log.read_text(errors="replace")[since:]
        sub_lines = [ln for ln in text.splitlines() if "(QoS" in ln]
        return all(any(t in ln for ln in sub_lines) for t in SENSOR_TOPICS)

    def offset(self) -> int:
        return self.log.stat().st_size


@pytest.fixture(scope="session")
def broker(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Broker]:
    if port_open(BROKER_PORT):
        pytest.fail(f"port {BROKER_PORT} already in use; stop the other broker first")
    log = tmp_path_factory.mktemp("mosq") / "mosquitto.log"
    fh = log.open("wb")
    proc = subprocess.Popen([MOSQUITTO, "-v", "-c", str(ROOT / "deploy/mosquitto-dev.conf")],
                            stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT)
    try:
        assert wait_for(lambda: port_open(BROKER_PORT), 10), "mosquitto did not start"
        yield Broker(log)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        fh.close()


# -- config ------------------------------------------------------------------------------------

def write_config(directory: Path, name: str = "solowatch.toml", port: int = BROKER_PORT,
                 supabase: bool = True) -> Path:
    """Write a temp config from the example: own SQLite path, chosen broker port."""
    text = (ROOT / "config/solowatch.example.toml").read_text(encoding="utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    db = directory / f"{Path(name).stem}.sqlite"
    text = text.replace('path = "data/raw/home.sqlite"', f'path = "{db}"')
    text = text.replace("port = 57883", f"port = {port}")
    if not supabase:
        text = re.sub(r"\[supabase\].*?(?=\n\[)", "", text, flags=re.DOTALL)
    out = directory / name
    out.write_text(text, encoding="utf-8")
    return out


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., Path]:
    def _make(name: str = "solowatch.toml", port: int = BROKER_PORT, supabase: bool = True
              ) -> Path:
        return write_config(tmp_path, name, port, supabase)
    return _make


def db_of(cfg: Path) -> Path:
    m = re.search(r'^path = "(.*)"$', cfg.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert m
    return Path(m.group(1))


def cli(*args: str, env: dict[str, str] | None = None, timeout: float = 120
        ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", "run", "solowatch", *args], check=False, cwd=ROOT, text=True,
                          capture_output=True, timeout=timeout, env=env or os.environ.copy())


def start_daemon(*args: str, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    return subprocess.Popen(["uv", "run", "solowatch", "daemon", *args], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env or os.environ.copy())


# -- Supabase ----------------------------------------------------------------------------------

def admin_client() -> Any:
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def family_client() -> Any:
    from supabase import create_client
    c = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    c.auth.sign_in_with_password({"email": FAMILY_EMAIL, "password": PASSWORD})
    return c


FAMILY_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-000000000001"
AWAY_NOTE = "e2e-chain"


def clean_supabase() -> None:
    db = admin_client()
    for table in ("alert_feedback", "alerts", "daily_reports"):
        db.table(table).delete().eq("household_id", DEMO_HID).execute()
    db.table("away_periods").delete().eq("household_id", DEMO_HID).eq("note", AWAY_NOTE).execute()


def seed_away(start: str, end: str) -> None:
    """The family registered an away period (as in the simulated scenario); the daemon polls it."""
    admin_client().table("away_periods").insert({
        "household_id": DEMO_HID, "start_date": start, "end_date": end,
        "note": AWAY_NOTE, "created_by": FAMILY_USER_ID}).execute()


@pytest.fixture
def clean_remote() -> Iterator[None]:
    """Demo household alerts/feedback/daily_reports removed at start and end."""
    clean_supabase()
    yield
    clean_supabase()


@pytest.fixture(scope="module")
def clean_remote_module() -> Iterator[None]:
    clean_supabase()
    yield
    clean_supabase()


@pytest.fixture(scope="session")
def e2e_env() -> dict[str, str]:
    """Environment for subprocesses: also exposes the E2E_* names the Playwright specs read."""
    env = os.environ.copy()
    env["E2E_SUPABASE_URL"] = env["SUPABASE_URL"]
    env["E2E_SERVICE_ROLE_KEY"] = env["SUPABASE_SERVICE_ROLE_KEY"]
    return env


# -- live demo: demo server, edge functions, push receiver -----------------------------------

DEMO_PORT = 8846
RECEIVER_PORT = 8843
FUNCTIONS_PORT = 57321


def _stop_group(proc: subprocess.Popen[Any]) -> None:
    import signal
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


@dataclass
class DemoServer:
    base: str
    log: Path

    def get(self, path: str) -> Any:
        import httpx
        return httpx.get(f"{self.base}{path}", timeout=30)

    def post(self, path: str, body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
        import httpx
        return httpx.post(f"{self.base}{path}", json=body, timeout=timeout)

    def ready(self) -> bool:
        try:
            r = self.get("/healthz")
            return bool(r.status_code == 200 and r.json().get("ready"))
        except Exception:  # noqa: BLE001 - not up yet
            return False


@pytest.fixture(scope="module")
def demo_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DemoServer]:
    """`solowatch demo-server` on 8846 with a temp store dir and the built web app."""
    if port_open(DEMO_PORT):
        pytest.fail(f"port {DEMO_PORT} already in use")
    work = tmp_path_factory.mktemp("demo")
    log = work / "demo-server.log"
    fh = log.open("wb")
    proc = subprocess.Popen(
        ["uv", "run", "solowatch", "demo-server", "--port", str(DEMO_PORT),
         "--store-dir", str(work / "store"), "--web-dist", str(ROOT / "web/dist")],
        cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, env=os.environ.copy(),
        start_new_session=True)
    server = DemoServer(f"http://localhost:{DEMO_PORT}", log)
    try:
        assert wait_for(server.ready, 60, 1.0), \
            f"demo server not ready in 60s: {log.read_text(errors='replace')[-800:]}"
        yield server
    finally:
        _stop_group(proc)
        fh.close()


@pytest.fixture(scope="session")
def functions_serve(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """`supabase functions serve push-alert` for the whole session (stopping it removes the runtime)."""
    import httpx
    log = tmp_path_factory.mktemp("fn") / "functions.log"
    fh = log.open("wb")
    proc = subprocess.Popen(
        ["supabase", "functions", "serve", "push-alert", "--env-file",
         "supabase/functions/.env", "--no-verify-jwt"],
        cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)

    def up() -> bool:
        try:
            r = httpx.options(f"http://localhost:{FUNCTIONS_PORT}/functions/v1/push-alert",
                              timeout=5)
            return r.status_code < 500
        except Exception:  # noqa: BLE001
            return False

    try:
        assert wait_for(up, 90, 2.0), \
            f"functions serve not up: {log.read_text(errors='replace')[-800:]}"
        yield
    finally:
        _stop_group(proc)
        fh.close()


@dataclass
class PushReceiver:
    out: Path

    def records(self) -> list[dict[str, Any]]:
        import json
        return [json.loads(ln) for ln in self.out.read_text(encoding="utf-8").splitlines() if ln]

    def count(self) -> int:
        return len(self.records())


@pytest.fixture
def push_receiver(tmp_path: Path) -> Iterator[PushReceiver]:
    """Fake push service on 8843, bound to all interfaces so docker reaches host.docker.internal."""
    if port_open(RECEIVER_PORT):
        pytest.fail(f"port {RECEIVER_PORT} already in use")
    out = tmp_path / "push.jsonl"
    proc = subprocess.Popen(
        ["uv", "run", "python", str(ROOT / "tests/e2e/push_receiver.py"),
         "--port", str(RECEIVER_PORT), "--out", str(out)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        assert wait_for(lambda: port_open(RECEIVER_PORT), 15), "push receiver did not start"
        yield PushReceiver(out)
    finally:
        _stop_group(proc)
