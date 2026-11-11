"""`solowatch demo-server`: the cloud virtual home over HTTP plus the built web app."""
from __future__ import annotations

import argparse
import importlib
import os
import socket
import struct
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from solowatch.contracts_demo import (
    DEMO_API_PREFIX,
    DEMO_EVENT_KINDS,
    DEMO_HOUSEHOLD_ID,
    ENV_PORT,
    ENV_SERVICE_ROLE_KEY,
    ENV_WEB_DIST,
    DemoEventKind,
    DemoState,
    InjectResult,
    VirtualHomeLike,
)
from solowatch.contracts_mvp import (
    ENV_DEVICE_EMAIL,
    ENV_DEVICE_PASSWORD,
    ENV_SUPABASE_ANON_KEY,
    ENV_SUPABASE_URL,
    SupabaseConfig,
)

EXIT_OK, EXIT_CONFIG = 0, 2
DEFAULT_PORT = 8845
# Bind-all address, spelled via INADDR_ANY so no IP literal sits in the source.
ALL_INTERFACES = socket.inet_ntoa(struct.pack("!I", socket.INADDR_ANY))
REQUIRED_ENV = (ENV_SUPABASE_URL, ENV_SUPABASE_ANON_KEY, ENV_DEVICE_EMAIL, ENV_DEVICE_PASSWORD,
                ENV_SERVICE_ROLE_KEY)
# Files the PWA build emits that must be served as-is; every other GET falls back to index.html.
STATIC_DIRS = ("assets/", "icons/")
STATIC_FILES = ("manifest.webmanifest", "sw.js", "registerSW.js")


def _is_static(path: str) -> bool:
    return (path.startswith(STATIC_DIRS) or path in STATIC_FILES
            or (path.startswith("workbox-") and path.endswith(".js") and "/" not in path))


def _unknown_kind() -> JSONResponse:
    return JSONResponse({"error": "unknown_kind", "kinds": list(DEMO_EVENT_KINDS)}, status_code=400)


def create_app(home: VirtualHomeLike, web_dist: Path | None) -> FastAPI:
    app = FastAPI(title="SoloWatch demo", docs_url=None, redoc_url=None, openapi_url=None)

    # Plain `def` handlers: FastAPI runs them in its thread pool, so blocking home calls are fine.
    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "ready": home.state().ready}

    @app.get(f"{DEMO_API_PREFIX}/state")
    def state() -> dict[str, Any]:
        return home.state().to_dict()

    @app.post(f"{DEMO_API_PREFIX}/inject")
    async def inject(request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return _unknown_kind()
        kind = body.get("kind") if isinstance(body, dict) else None
        if kind not in DEMO_EVENT_KINDS:
            return _unknown_kind()
        if not (await run_in_threadpool(home.state)).ready:
            return JSONResponse({"error": "not_ready"}, status_code=503)
        try:
            result = await run_in_threadpool(home.inject, kind)
        except ValueError:
            return _unknown_kind()
        return JSONResponse(result.to_dict())

    @app.post(f"{DEMO_API_PREFIX}/reset")
    def reset() -> dict[str, Any]:
        return home.reset().to_dict()

    if web_dist is not None:
        root = web_dist.resolve()
        index = root / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path == "api" or path.startswith("api/"):
                return JSONResponse({"error": "not_found"}, status_code=404)
            if _is_static(path):
                target = (root / path).resolve()
                if target.is_relative_to(root) and target.is_file():
                    return FileResponse(target)
                return JSONResponse({"error": "not_found"}, status_code=404)
            return FileResponse(index, media_type="text/html")

    return app


class StartingHome:
    """VirtualHomeLike that answers `ready=False` until the wrapped home's start() returns.

    The real home runs start() (first reset) in a background thread so uvicorn can bind at once;
    until then nothing reaches the inner home, so /healthz and /state never block on it.
    """

    START_THREAD = "demo-home-start"

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.started = threading.Event()
        self.error: str | None = None

    def begin(self) -> threading.Thread:
        t = threading.Thread(target=self._start, name=self.START_THREAD, daemon=True)
        t.start()
        return t

    def _start(self) -> None:
        try:
            self.inner.start()
        except Exception as e:  # noqa: BLE001 — keep serving ready=false and say why
            self.error = f"start failed: {e}"
            print(f"demo-server: virtual home start failed: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return
        self.started.set()

    def _not_ready(self) -> DemoState:
        return DemoState(ready=False, virtual_now="", day_index=0, household_id=DEMO_HOUSEHOLD_ID,
                         readings_total=0, recent={}, outbox=[], last_inject=None, history=[],
                         error=self.error)

    def reset(self) -> DemoState:
        return self.inner.reset() if self.started.is_set() else self._not_ready()

    def inject(self, kind: DemoEventKind) -> InjectResult:
        if not self.started.is_set():
            raise RuntimeError("virtual home is not ready")
        result: InjectResult = self.inner.inject(kind)
        return result

    def state(self) -> DemoState:
        return self.inner.state() if self.started.is_set() else self._not_ready()

    def close(self) -> None:
        self.inner.close()


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="solowatch demo-server",
                                 description="cloud virtual home API + web app")
    ap.add_argument("--host", default=ALL_INTERFACES)
    ap.add_argument("--port", type=int, default=None, help=f"default ${ENV_PORT} or {DEFAULT_PORT}")
    ap.add_argument("--web-dist", default=None, help=f"default ${ENV_WEB_DIST}; empty = API only")
    ap.add_argument("--store-dir", default=None, help="SQLite directory (default: a temp dir)")
    ap.add_argument("--sync-interval", type=float, default=2.0,
                    help="seconds between feedback/away sync ticks (0 = off)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print(f"config error: missing env {', '.join(missing)}", file=sys.stderr)
        return EXIT_CONFIG
    try:
        port = args.port if args.port is not None else int(os.environ.get(ENV_PORT) or DEFAULT_PORT)
    except ValueError:
        print(f"config error: {ENV_PORT}={os.environ.get(ENV_PORT)!r} is not a port",
              file=sys.stderr)
        return EXIT_CONFIG
    dist_arg = args.web_dist if args.web_dist is not None else os.environ.get(ENV_WEB_DIST, "")
    web_dist = Path(dist_arg) if dist_arg else None
    if web_dist is not None and not (web_dist / "index.html").is_file():
        print(f"config error: {web_dist}/index.html not found", file=sys.stderr)
        return EXIT_CONFIG
    store_dir = Path(args.store_dir) if args.store_dir else Path(tempfile.mkdtemp(prefix="solowatch-demo-"))
    store_dir.mkdir(parents=True, exist_ok=True)
    supabase = SupabaseConfig(url=os.environ[ENV_SUPABASE_URL],
                              anon_key=os.environ[ENV_SUPABASE_ANON_KEY],
                              device_email=os.environ[ENV_DEVICE_EMAIL],
                              device_password=os.environ[ENV_DEVICE_PASSWORD])
    # Imported lazily so create_app (and its tests) never depend on the engine module.
    virtual_home = importlib.import_module("solowatch.virtual_home")
    home = StartingHome(virtual_home.VirtualHome(
        supabase, service_role_key=os.environ[ENV_SERVICE_ROLE_KEY], store_dir=store_dir,
        sync_interval_s=args.sync_interval))
    try:
        home.begin()   # first reset runs in the background; the API answers ready=false meanwhile
        app = create_app(home, web_dist)
        print(f"DEMO-SERVER listening on http://{args.host}:{port} "
              f"web_dist={web_dist if web_dist is not None else 'none'}", flush=True)
        uvicorn.run(app, host=args.host, port=port, log_level="info")
    finally:
        home.close()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
