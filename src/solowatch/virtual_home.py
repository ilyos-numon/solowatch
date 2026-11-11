"""Cloud virtual home: simulate_home -> SqliteStore -> the existing Daemon, in-process, no MQTT.

One button press = one virtual day. All state lives on a single worker thread (sqlite3 rule);
scores are read from the daemon's river scorers, never computed here.
"""
from __future__ import annotations

import dataclasses
import logging
import shutil
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from river.anomaly import GaussianScorer
from supabase import create_client

from solowatch.contracts import TZ, WINDOWS, day_type, window_of
from solowatch.contracts_demo import (
    DEMO_AWAY,
    DEMO_AWAY_NOTE,
    DEMO_EVENT_KINDS,
    DEMO_FAMILY_USER_ID,
    DEMO_HOUSEHOLD_ID,
    DEMO_MAX_DAYS,
    DEMO_SEED_BASE,
    DEMO_START,
    OUTBOX_LIMIT,
    RECENT_SLOTS,
    DemoEventKind,
    DemoState,
    InjectResult,
    OutboxEntry,
    ScoreEntry,
)
from solowatch.contracts_mvp import (
    DEFAULT_HOME,
    DEFAULT_SENSORS,
    DEMO_HOUSEHOLD_NAME,
    DEMO_HOUSEHOLD_SLUG,
    WINDOW_LABEL_KO,
    AlertPayload,
    AppConfig,
    AwayPeriod,
    DailyReportPayload,
    DetectorConfig,
    FeedbackRow,
    HomeScenario,
    InjectedEvent,
    MqttConfig,
    SupabaseConfig,
)
from solowatch.daemon import Daemon, learn_until
from solowatch.ops_report import VERDICT_KO
from solowatch.policy import HomePolicy
from solowatch.simulate_home import simulate_home
from solowatch.sinks import AppriseSink, SupabaseSink
from solowatch.store import SqliteStore

log = logging.getLogger(__name__)

T = TypeVar("T")
_UNIT = {s.sensor_id: s.unit for s in DEFAULT_SENSORS}


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), TZ)


def _now_iso() -> str:
    return datetime.now(TZ).isoformat()


def _jsonable(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in dataclasses.asdict(obj).items():
        out[k] = v.isoformat() if isinstance(v, date | datetime) else v
    return out


class VirtualClock:
    def __init__(self, start: datetime) -> None:
        self._now = start.astimezone(TZ)

    def now(self) -> datetime:
        return self._now

    def advance_days(self, n: int) -> None:
        self._now = self._now + timedelta(days=n)


class RecordingSupabaseSink(SupabaseSink):
    """SupabaseSink that also remembers every row that left (or came back into) the house."""

    def __init__(self, cfg: SupabaseConfig) -> None:
        super().__init__(cfg)
        self.outbox: list[OutboxEntry] = []
        self._last_away: frozenset[tuple[str, str, str]] | None = None

    def _record(self, direction: str, table: str, summary: str, row: dict[str, Any]) -> None:
        entry = OutboxEntry(_now_iso(), direction, table, summary, row)  # type: ignore[arg-type]
        self.outbox.insert(0, entry)
        del self.outbox[OUTBOX_LIMIT:]

    def _clear(self) -> None:
        self.outbox.clear()
        self._last_away = None

    def send_alert(self, p: AlertPayload) -> str:
        remote = super().send_alert(p)
        self._record("out", "alerts", p.sentence, p.to_row())
        return remote

    def send_daily(self, p: DailyReportPayload) -> str:
        remote = super().send_daily(p)
        self._record("out", "daily_reports", f"일일 요약 {p.day.isoformat()} · {p.sentence}",
                     p.to_row())
        return remote

    def fetch_feedback(self, household_id: str, since: datetime | None) -> list[FeedbackRow]:
        rows = super().fetch_feedback(household_id, since)
        for r in rows:
            self._record("in", "alert_feedback", VERDICT_KO.get(r.verdict, r.verdict), _jsonable(r))
        return rows

    def fetch_away(self, household_id: str) -> list[AwayPeriod]:
        periods = super().fetch_away(household_id)
        key = frozenset((p.start_date.isoformat(), p.end_date.isoformat(), p.note) for p in periods)
        if key != self._last_away:
            self._last_away = key
            for p in periods:
                self._record("in", "away_periods",
                             f"외출 {p.start_date:%m-%d} ~ {p.end_date:%m-%d}", _jsonable(p))
            if not periods:
                self._record("in", "away_periods", "외출 없음", {})
        return periods


class VirtualHome:
    def __init__(self, supabase: SupabaseConfig | None, service_role_key: str = "",
                 store_dir: Path | None = None, scenario: HomeScenario = DEFAULT_HOME,
                 start: date = DEMO_START, sync_interval_s: float = 2.0) -> None:
        self._supabase_cfg = supabase
        self._service_role_key = service_role_key
        self._own_dir = store_dir is None
        self._dir = Path(tempfile.mkdtemp(prefix="solowatch-demo-")) if store_dir is None \
            else store_dir
        self._scenario = scenario
        self._start = start
        self._sync_interval = sync_interval_s
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="virtual-home")
        self._stop = threading.Event()
        self._timer: threading.Thread | None = None
        self._sink = RecordingSupabaseSink(supabase) if supabase is not None else None
        self._clock = VirtualClock(_midnight(start))
        self._store: SqliteStore | None = None
        self._policy: HomePolicy | None = None
        self._daemon: Daemon | None = None
        self._ready = False
        self._day_index = 0
        self._history: list[dict[str, Any]] = []
        self._last_inject: InjectResult | None = None
        self._previous: dict[str, list[ScoreEntry]] = {}
        self._feedback_seen = 0
        self._error: str | None = None
        self._closed = False

    # -- public API (every call runs on the single worker) ------------------------------------

    def _run(self, fn: Callable[[], T]) -> T:
        return self._pool.submit(fn).result()

    def start(self) -> None:
        self.reset()
        if self._sync_interval > 0 and self._timer is None:
            self._timer = threading.Thread(target=self._sync_loop, name="virtual-home-sync",
                                           daemon=True)
            self._timer.start()

    def sync(self) -> int:
        return self._run(self._sync)

    def reset(self) -> DemoState:
        def run() -> DemoState:
            self._reset()
            return self._state()
        return self._run(run)

    def inject(self, kind: DemoEventKind) -> InjectResult:
        if kind not in DEMO_EVENT_KINDS:
            raise ValueError(f"unknown demo event kind: {kind!r}")
        return self._run(lambda: self._inject(kind))

    def state(self) -> DemoState:
        return self._run(self._state)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._timer is not None:
            self._timer.join(timeout=5)
        self._pool.submit(self._close_store).result()
        self._pool.shutdown(wait=True)
        if self._own_dir:
            shutil.rmtree(self._dir, ignore_errors=True)

    # -- worker-side implementation -----------------------------------------------------------

    def _sync_loop(self) -> None:
        while not self._stop.wait(self._sync_interval):
            try:
                self.sync()
            except RuntimeError:  # pool shut down during close()
                return
            except Exception as e:  # noqa: BLE001 - the sync thread must outlive one bad tick
                log.warning("virtual home sync failed: %s", e)
                self._error = str(e)

    def _close_store(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def _reset_remote(self) -> None:
        """Clear the demo household's rows in Supabase and re-seed the away period."""
        cfg = self._supabase_cfg
        if cfg is None:
            return
        if not self._service_role_key:
            log.warning("no service role key: skipping Supabase demo cleanup")
            return
        db = create_client(cfg.url, self._service_role_key)
        for table in ("alert_feedback", "alerts", "daily_reports"):
            db.table(table).delete().eq("household_id", DEMO_HOUSEHOLD_ID).execute()
        db.table("away_periods").delete().eq("household_id", DEMO_HOUSEHOLD_ID) \
            .eq("note", DEMO_AWAY_NOTE).execute()
        db.table("away_periods").insert({
            "household_id": DEMO_HOUSEHOLD_ID, "start_date": DEMO_AWAY[0].isoformat(),
            "end_date": DEMO_AWAY[1].isoformat(), "created_by": DEMO_FAMILY_USER_ID,
            "note": DEMO_AWAY_NOTE}).execute()

    def _reset(self) -> None:
        self._ready = False
        try:
            self._reset_remote()
            self._close_store()
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / "home.sqlite"
            path.unlink(missing_ok=True)
            store = SqliteStore(str(path))
            for readings in simulate_home(self._scenario).values():
                store.insert_readings(readings)
            # Same away period Supabase gets; the daemon's away poll replaces it when online.
            store.replace_away([AwayPeriod(DEMO_AWAY[0], DEMO_AWAY[1], DEMO_AWAY_NOTE)])
            cfg = AppConfig(
                household_id=DEMO_HOUSEHOLD_ID, slug=DEMO_HOUSEHOLD_SLUG, name=DEMO_HOUSEHOLD_NAME,
                mqtt=MqttConfig("", 0), store_path=str(path), detector=DetectorConfig(),
                supabase=self._supabase_cfg, apprise_urls=(), sensors=DEFAULT_SENSORS,
                install_start=self._scenario.start)
            policy = HomePolicy(DEFAULT_SENSORS, learn_until(cfg, store))
            if self._sink is not None:
                self._sink._clear()
            self._clock = VirtualClock(_midnight(self._start))
            daemon = Daemon(cfg, store, policy, ingester=None, supabase=self._sink,
                            apprise=AppriseSink(()), clock=self._clock.now)
            self._store, self._policy, self._daemon = store, policy, daemon
            self._feedback_seen = 0
            self._day_index = 0
            self._history = []
            self._last_inject = None
            self._previous = {}
            self._tick()
            self._error = None
            self._ready = True
        except Exception as e:
            self._error = f"reset failed: {e}"
            raise

    def _tick(self) -> int:
        assert self._daemon is not None
        result = self._daemon.tick()
        self._record_feedback()
        return result.feedback_applied

    def _record_feedback(self) -> None:
        """Turn new Daemon.feedback_log items into outbox lines with the learned mean shift."""
        assert self._daemon is not None
        new = self._daemon.feedback_log[self._feedback_seen:]
        self._feedback_seen = len(self._daemon.feedback_log)
        if not new or self._sink is None:
            return
        outbox = self._sink.outbox
        for item in new:
            fid = item["feedback_id"]
            raw = next((o for o in outbox if o.table == "alert_feedback"
                        and o.row.get("id") == fid and " · " not in o.summary), None)
            row = dict(raw.row) if raw is not None else {"id": fid}
            if raw is not None:
                outbox.remove(raw)
            window = window_of(datetime.fromisoformat(item["window_start"]).astimezone(TZ))
            summary = (f"{VERDICT_KO.get(item['verdict'], item['verdict'])} · "
                       f"{WINDOW_LABEL_KO[window]} 창 평소 {item['mean_before']:.1f} → "
                       f"{item['mean_after']:.1f} {_UNIT.get(item['sensor_id'], '')}")
            row.update({k: item[k] for k in ("sensor_id", "window_start", "mean_before",
                                             "mean_after")})
            outbox.insert(0, OutboxEntry(_now_iso(), "in", "alert_feedback", summary, row))
        del outbox[OUTBOX_LIMIT:]

    def _sync(self) -> int:
        if self._daemon is None:
            return 0
        return self._tick()

    def _scores(self, day: date) -> list[tuple[str, str, str, float, float, float]]:
        assert self._store is not None and self._policy is not None
        out: list[tuple[str, str, str, float, float, float]] = []
        for spec in DEFAULT_SENSORS:
            sid = spec.sensor_id
            for window, (lo, hi) in WINDOWS.items():
                ws = _midnight(day) + timedelta(hours=lo)
                we = _midnight(day) + timedelta(hours=hi)
                actual = float(sum(u.value for u in self._store.hourly_usage(sid, ws, we)))
                dtype = day_type(ws)
                scorer = self._policy.detector(sid).models()[(dtype, window)]
                assert isinstance(scorer, GaussianScorer)
                score = float(scorer.score_one(None, actual))
                expected = float(scorer.gaussian.mu)
                out.append((sid, window, dtype, score, expected, actual))
        return out

    def _inject(self, kind: DemoEventKind) -> InjectResult:
        auto_reset = False
        if self._daemon is None:
            self._reset()
        elif self._day_index >= DEMO_MAX_DAYS:
            self._reset()
            auto_reset = True
        assert self._store is not None and self._daemon is not None
        day = self._start + timedelta(days=self._day_index)
        self._tick()  # pick up feedback / away before the new day is scored
        scenario = dataclasses.replace(
            self._scenario, start=day, days=1, seed=DEMO_SEED_BASE + self._day_index,
            learn_days=0, events=() if kind == "normal" else (InjectedEvent(kind, day),), away=())
        readings = 0
        for rs in simulate_home(scenario).values():
            readings += self._store.insert_readings(rs)
        raw_scores = self._scores(day)
        self._clock.advance_days(1)
        tick = self._daemon.tick()
        self._record_feedback()
        flagged = {(a.sensor_id, a.window_start.astimezone(TZ)) for spec in DEFAULT_SENSORS
                   for a in self._store.list_anomalies(spec.sensor_id)}
        scores = [ScoreEntry(sid, window, dtype, score, expected, actual,
                             (sid, _midnight(day) + timedelta(hours=WINDOWS[window][0]))  # type: ignore[index]
                             in flagged)
                  for sid, window, dtype, score, expected, actual in raw_scores]
        alerts = [{"remote_id": la.remote_id or la.id, "sentence": la.payload.sentence,
                   "window_start": la.payload.window_start.astimezone(TZ).isoformat()}
                  for la in self._store.list_alert_log()
                  if la.payload.kind == "anomaly"
                  and la.payload.window_start.astimezone(TZ).date() == day]
        result = InjectResult(
            kind=kind, day=day.isoformat(), day_type=day_type(_midnight(day)), readings=readings,
            alerts=alerts, scores=scores, previous_scores=list(self._previous.get(kind, [])),
            daily_sent=tick.daily_sent, auto_reset=auto_reset)
        self._previous[kind] = scores
        self._day_index += 1
        self._history.append({"day": day.isoformat(), "kind": kind, "alerts": len(alerts)})
        self._last_inject = result
        return result

    def _state(self) -> DemoState:
        recent: dict[str, list[list[Any]]] = {}
        total = 0
        if self._store is not None:
            total = self._store.count_readings()
            for spec in DEFAULT_SENSORS:
                rows = self._store._con.execute(
                    "SELECT ts, value FROM readings WHERE sensor_id = ? ORDER BY ts DESC LIMIT ?",
                    (spec.sensor_id, RECENT_SLOTS)).fetchall()
                recent[spec.sensor_id] = [[ts, float(v)] for ts, v in reversed(rows)]
        outbox = list(self._sink.outbox) if self._sink is not None else []
        return DemoState(
            ready=self._ready, virtual_now=self._clock.now().isoformat(),
            day_index=self._day_index, household_id=DEMO_HOUSEHOLD_ID, readings_total=total,
            recent=recent, outbox=outbox, last_inject=self._last_inject,
            history=list(self._history), error=self._error)
