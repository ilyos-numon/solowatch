from __future__ import annotations

import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from solowatch import demo_server
from solowatch.contracts_demo import (
    DEMO_EVENT_KINDS,
    DEMO_HOUSEHOLD_ID,
    DemoEventKind,
    DemoState,
    InjectResult,
    OutboxEntry,
    ScoreEntry,
)

ENV_NAMES = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SOLOWATCH_DEVICE_EMAIL",
             "SOLOWATCH_DEVICE_PASSWORD", "SUPABASE_SERVICE_ROLE_KEY")


def _state(ready: bool = True, day_index: int = 0) -> DemoState:
    return DemoState(
        ready=ready, virtual_now="2026-11-02T00:00:00+09:00", day_index=day_index,
        household_id=DEMO_HOUSEHOLD_ID, readings_total=32256,
        recent={"water_main": [["2026-11-01T23:55:00+09:00", 0.0]]},
        outbox=[OutboxEntry(at="2026-11-03T10:00:00+09:00", direction="out", table="alerts",
                            summary="아침 물 사용이 없습니다", row={"sentence": "x"})],
        last_inject=None, history=[], error=None)


class FakeHome:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.calls: list[str] = []

    def reset(self) -> DemoState:
        self.calls.append("reset")
        return _state(self.ready, 0)

    def inject(self, kind: DemoEventKind) -> InjectResult:
        if kind not in DEMO_EVENT_KINDS:
            raise ValueError(kind)
        self.calls.append(f"inject:{kind}")
        score = ScoreEntry("water_main", "morning", "weekday", 0.99, 30.0, 0.0, True)
        return InjectResult(kind=kind, day="2026-11-02", day_type="weekday", readings=1152,
                            alerts=[{"remote_id": "r1", "sentence": "s",
                                     "window_start": "2026-11-02T06:00:00+09:00"}],
                            scores=[score], previous_scores=[], daily_sent=True,
                            auto_reset=False)

    def state(self) -> DemoState:
        self.calls.append("state")
        return _state(self.ready, 3)

    def close(self) -> None:
        self.calls.append("close")


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "icons").mkdir()
    (d / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    (d / "assets" / "a.js").write_text("console.log('A')", encoding="utf-8")
    (d / "icons" / "icon-192.png").write_bytes(b"\x89PNG")
    (d / "manifest.webmanifest").write_text('{"name":"m"}', encoding="utf-8")
    (d / "sw.js").write_text("// sw", encoding="utf-8")
    (d / "registerSW.js").write_text("// reg", encoding="utf-8")
    (d / "workbox-abc123.js").write_text("// wb", encoding="utf-8")
    return d


def test_healthz_reports_ready() -> None:
    c = TestClient(demo_server.create_app(FakeHome(), None))
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "ready": True}
    r2 = TestClient(demo_server.create_app(FakeHome(ready=False), None)).get("/healthz")
    assert r2.json() == {"ok": True, "ready": False}


def test_state_returns_fake_state_json() -> None:
    r = TestClient(demo_server.create_app(FakeHome(), None)).get("/api/demo/state")
    assert r.status_code == 200
    body = r.json()
    assert body["day_index"] == 3
    assert body["household_id"] == DEMO_HOUSEHOLD_ID
    assert body["outbox"][0]["table"] == "alerts"
    assert body["recent"]["water_main"][0] == ["2026-11-01T23:55:00+09:00", 0.0]


def test_inject_ok() -> None:
    home = FakeHome()
    r = TestClient(demo_server.create_app(home, None)).post(
        "/api/demo/inject", json={"kind": "no_morning_water"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "no_morning_water"
    assert body["readings"] == 1152
    assert body["scores"][0]["sensor_id"] == "water_main"
    assert "inject:no_morning_water" in home.calls


@pytest.mark.parametrize("payload", [{"kind": "earthquake"}, {}, {"kind": 3}])
def test_inject_unknown_kind_400(payload: dict[str, Any]) -> None:
    home = FakeHome()
    r = TestClient(demo_server.create_app(home, None)).post("/api/demo/inject", json=payload)
    assert r.status_code == 400
    assert r.json() == {"error": "unknown_kind", "kinds": list(DEMO_EVENT_KINDS)}
    assert not any(c.startswith("inject") for c in home.calls)


def test_inject_bad_json_400() -> None:
    r = TestClient(demo_server.create_app(FakeHome(), None)).post(
        "/api/demo/inject", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"] == "unknown_kind"


def test_inject_not_ready_503() -> None:
    home = FakeHome(ready=False)
    r = TestClient(demo_server.create_app(home, None)).post(
        "/api/demo/inject", json={"kind": "normal"})
    assert r.status_code == 503
    assert r.json() == {"error": "not_ready"}
    assert not any(c.startswith("inject") for c in home.calls)


def test_reset_ok() -> None:
    home = FakeHome()
    r = TestClient(demo_server.create_app(home, None)).post("/api/demo/reset")
    assert r.status_code == 200
    assert r.json()["day_index"] == 0
    assert "reset" in home.calls


def test_no_dist_serves_api_only() -> None:
    c = TestClient(demo_server.create_app(FakeHome(), None))
    assert c.get("/").status_code == 404
    assert c.get("/healthz").status_code == 200


@pytest.mark.parametrize("path", ["/", "/demo", "/login", "/anything/deep"])
def test_spa_fallback_serves_index(dist: Path, path: str) -> None:
    r = TestClient(demo_server.create_app(FakeHome(), dist)).get(path)
    assert r.status_code == 200
    assert r.text == "<html>INDEX</html>"
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize(("path", "text"), [
    ("/assets/a.js", "console.log('A')"),
    ("/manifest.webmanifest", '{"name":"m"}'),
    ("/sw.js", "// sw"),
    ("/registerSW.js", "// reg"),
    ("/workbox-abc123.js", "// wb"),
])
def test_static_files_served_as_is(dist: Path, path: str, text: str) -> None:
    r = TestClient(demo_server.create_app(FakeHome(), dist)).get(path)
    assert r.status_code == 200
    assert r.text == text


def test_icons_served(dist: Path) -> None:
    r = TestClient(demo_server.create_app(FakeHome(), dist)).get("/icons/icon-192.png")
    assert r.status_code == 200
    assert r.content == b"\x89PNG"


def test_missing_asset_is_404_and_api_not_shadowed(dist: Path) -> None:
    c = TestClient(demo_server.create_app(FakeHome(), dist))
    assert c.get("/assets/missing.js").status_code == 404
    assert c.get("/assets/../index.html").status_code in (200, 404)
    assert c.get("/api/demo/state").json()["day_index"] == 3
    assert c.get("/api/demo/nope").status_code == 404


def test_main_missing_env_exits_2(monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert demo_server.main([]) == 2
    err = capsys.readouterr().err
    for name in ENV_NAMES:
        assert name in err


def _join_start_thread() -> None:
    for t in threading.enumerate():
        if t.name == demo_server.StartingHome.START_THREAD:
            t.join(timeout=10)
            assert not t.is_alive()


def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.setenv(name, "v")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("SOLOWATCH_WEB_DIST", raising=False)


def _install_virtual_home(monkeypatch: pytest.MonkeyPatch, cls: type) -> None:
    fake_mod = types.ModuleType("solowatch.virtual_home")
    fake_mod.VirtualHome = cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "solowatch.virtual_home", fake_mod)


def test_main_serves_not_ready_while_start_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    release = threading.Event()
    entered = threading.Event()
    homes: list[FakeHome] = []

    class SlowHome(FakeHome):
        def __init__(self, supabase: Any, **kw: Any) -> None:
            super().__init__()
            homes.append(self)

        def start(self) -> None:
            entered.set()
            assert release.wait(timeout=10)
            self.calls.append("start")

    _install_virtual_home(monkeypatch, SlowHome)
    seen: dict[str, Any] = {}

    def fake_run(app: Any, host: str, port: int, **kw: Any) -> None:
        # uvicorn is reached while start() is still blocked inside the background thread.
        assert entered.wait(timeout=10)
        c = TestClient(app)
        seen["health_before"] = c.get("/healthz").json()
        seen["state_before"] = c.get("/api/demo/state").json()["ready"]
        inj = c.post("/api/demo/inject", json={"kind": "normal"})
        seen["inject_before"] = (inj.status_code, inj.json())
        seen["calls_before"] = list(homes[0].calls)
        release.set()
        _join_start_thread()
        seen["health_after"] = c.get("/healthz").json()
        seen["inject_after"] = c.post("/api/demo/inject", json={"kind": "normal"}).status_code

    monkeypatch.setattr(demo_server.uvicorn, "run", fake_run)
    assert demo_server.main([]) == 0
    assert seen["health_before"] == {"ok": True, "ready": False}
    assert seen["state_before"] is False
    assert seen["inject_before"] == (503, {"error": "not_ready"})
    assert seen["calls_before"] == []          # nothing reached the home before start() returned
    assert seen["health_after"] == {"ok": True, "ready": True}
    assert seen["inject_after"] == 200
    assert homes[0].calls[-1] == "close"


def test_main_start_failure_logged_and_stays_not_ready(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _set_env(monkeypatch)

    class BrokenHome(FakeHome):
        def __init__(self, supabase: Any, **kw: Any) -> None:
            super().__init__()

        def start(self) -> None:
            raise RuntimeError("supabase unreachable")

    _install_virtual_home(monkeypatch, BrokenHome)
    seen: dict[str, Any] = {}

    def fake_run(app: Any, host: str, port: int, **kw: Any) -> None:
        _join_start_thread()
        c = TestClient(app)
        seen["health"] = c.get("/healthz").json()
        seen["error"] = c.get("/api/demo/state").json()["error"]
        seen["inject"] = c.post("/api/demo/inject", json={"kind": "normal"}).status_code

    monkeypatch.setattr(demo_server.uvicorn, "run", fake_run)
    assert demo_server.main([]) == 0
    assert seen["health"] == {"ok": True, "ready": False}
    assert "supabase unreachable" in seen["error"]
    assert seen["inject"] == 503
    assert "supabase unreachable" in capsys.readouterr().err


def test_main_builds_home_and_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                   dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name in ENV_NAMES:
        monkeypatch.setenv(name, f"v-{name}")
    monkeypatch.delenv("PORT", raising=False)
    made: list[dict[str, Any]] = []
    homes: list[FakeHome] = []

    class FakeVirtualHome(FakeHome):
        def __init__(self, supabase: Any, service_role_key: str = "",
                     store_dir: Path | None = None, sync_interval_s: float = 2.0) -> None:
            super().__init__()
            made.append({"supabase": supabase, "key": service_role_key,
                         "store_dir": store_dir, "sync": sync_interval_s})
            homes.append(self)

        def start(self) -> None:
            self.calls.append("start")

    fake_mod = types.ModuleType("solowatch.virtual_home")
    fake_mod.VirtualHome = FakeVirtualHome  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "solowatch.virtual_home", fake_mod)
    ran: list[tuple[str, int]] = []

    def fake_run(app: Any, host: str, port: int, **kw: Any) -> None:
        _join_start_thread()
        ran.append((host, port))

    monkeypatch.setattr(demo_server.uvicorn, "run", fake_run)

    code = demo_server.main(["--host", "localhost", "--web-dist", str(dist),
                             "--store-dir", str(tmp_path / "st"), "--sync-interval", "0"])
    assert code == 0
    assert ran == [("localhost", 8845)]
    cfg = made[0]["supabase"]
    assert cfg.url == "v-SUPABASE_URL" and cfg.device_password == "v-SOLOWATCH_DEVICE_PASSWORD"
    assert made[0]["key"] == "v-SUPABASE_SERVICE_ROLE_KEY"
    assert made[0]["store_dir"] == tmp_path / "st"
    assert made[0]["sync"] == 0.0
    assert homes[0].calls[0] == "start" and homes[0].calls[-1] == "close"
    out = capsys.readouterr().out
    assert f"DEMO-SERVER listening on http://localhost:8845 web_dist={dist}" in out


def test_main_port_env_and_no_dist(monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    for name in ENV_NAMES:
        monkeypatch.setenv(name, "v")
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.delenv("SOLOWATCH_WEB_DIST", raising=False)

    class FakeVirtualHome(FakeHome):
        def __init__(self, supabase: Any, **kw: Any) -> None:
            super().__init__()

        def start(self) -> None:
            pass

    fake_mod = types.ModuleType("solowatch.virtual_home")
    fake_mod.VirtualHome = FakeVirtualHome  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "solowatch.virtual_home", fake_mod)
    ran: list[int] = []
    monkeypatch.setattr(demo_server.uvicorn, "run", lambda app, host, port, **kw: ran.append(port))
    assert demo_server.main([]) == 0
    assert ran == [9123]
    expected = f"DEMO-SERVER listening on http://{demo_server.ALL_INTERFACES}:9123 web_dist=none"
    assert expected in capsys.readouterr().out
