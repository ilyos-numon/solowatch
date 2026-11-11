"""`solowatch daemon`: MQTT -> store -> HomePolicy -> sentences -> sinks, plus feedback/away polling.

One synchronous tick loop (design decision 11); systemd keeps it running. The modules it joins do
the work: paho (Ingester), river (HomePolicy), supabase-py/apprise (sinks).
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from solowatch.alerts import compose_alert, compose_daily
from solowatch.contracts import TZ, Anomaly, day_type, window_of, window_start
from solowatch.contracts_mvp import AppConfig, ConfigError
from solowatch.mqtt_ingest import BrokerUnreachable, Ingester
from solowatch.policy import HomePolicy
from solowatch.sensors_config import load_config
from solowatch.sinks import AppriseSink, SinkError, SupabaseSink, deliver
from solowatch.store import SqliteStore

log = logging.getLogger(__name__)

EXIT_OK, EXIT_CONFIG, EXIT_BROKER = 0, 2, 3
FEEDBACK_CURSOR = "feedback_since"


def _hour_cursor(sensor_id: str) -> str:
    return f"hour:{sensor_id}"


def _daily_cursor(day: date) -> str:
    return f"daily:{day.isoformat()}"


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), TZ)


def learn_until(cfg: AppConfig, store: SqliteStore, today: date | None = None) -> datetime:
    """(install_start or first reading's local date, else today) + learn_days."""
    start = cfg.install_start
    if start is None:
        # The Store protocol has no "first reading" query; read it from the same connection.
        row = store._con.execute("SELECT MIN(ts) FROM readings").fetchone()
        if row and row[0]:
            start = datetime.fromisoformat(row[0]).astimezone(TZ).date()
        else:
            start = today or datetime.now(TZ).date()
    return _midnight(start) + timedelta(days=cfg.detector.learn_days)


@dataclass
class TickResult:
    readings: int
    alerts: int
    feedback_applied: int
    daily_sent: bool


class Daemon:
    def __init__(self, cfg: AppConfig, store: SqliteStore, policy: HomePolicy,
                 ingester: Ingester | None, supabase: SupabaseSink | None,
                 apprise: AppriseSink, clock: Callable[[], datetime]) -> None:
        self.cfg = cfg
        self.store = store
        self.policy = policy
        self.ingester = ingester
        self.supabase = supabase
        self.apprise = apprise
        self.clock = clock
        self.connect_timeout = 15.0
        self.feedback_log: list[dict[str, Any]] = []
        self.last: TickResult | None = None
        self._stop = False
        self._sensors = {s.sensor_id: s for s in cfg.sensors}
        first = cfg.sensors[0].sensor_id
        self._origin = policy.detector(first).learn_until - timedelta(days=cfg.detector.learn_days)
        self._restore()

    # -- startup -------------------------------------------------------------------------------

    def _restore(self) -> None:
        """Rebuild river state after a restart: replay processed windows, then applied feedback."""
        self.policy.set_away(self.store.list_away())
        for sid in self._sensors:
            cursor = self.store.get_cursor(_hour_cursor(sid))
            if cursor is None:
                continue
            end = datetime.fromisoformat(cursor)
            self.policy.process(sid, self.store.hourly_usage(sid, self._origin, end))
            self.policy.flush(sid)
        pending = {f.id for f in self.store.unapplied_feedback()}
        alerts = self._alert_ids()
        for f in self.store.list_feedback():
            if f.id in pending or f.alert_id is None or f.alert_id not in alerts:
                continue
            for a in self.store.anomalies_for_alert(alerts[f.alert_id]):
                self.policy.apply_feedback(a, f.verdict)

    def _alert_ids(self) -> dict[str, str]:
        """remote_id (and local id) -> local alerts_log id."""
        out: dict[str, str] = {}
        for la in self.store.list_alert_log():
            out[la.id] = la.id
            if la.remote_id:
                out[la.remote_id] = la.id
        return out

    # -- tick ----------------------------------------------------------------------------------

    def tick(self) -> TickResult:
        now = self.clock().astimezone(TZ)
        readings = self.ingester.flush() if self.ingester is not None else 0
        self._sync_away()
        alerts = self._detect(now)
        self._send_unsent()
        applied = self._apply_feedback()
        daily = self._daily(now)
        self.last = TickResult(readings, alerts, applied, daily)
        return self.last

    def _sync_away(self) -> None:
        if self.supabase is not None:
            try:
                self.store.replace_away(self.supabase.fetch_away(self.cfg.household_id))
            except SinkError as e:
                log.warning("away poll failed, keeping stored periods: %s", e)
        self.policy.set_away(self.store.list_away())

    def _detect(self, now: datetime) -> int:
        end = window_start(now)  # every window ending at or before now is closed
        found: list[Anomaly] = []
        for sid in self._sensors:
            name = _hour_cursor(sid)
            cursor = self.store.get_cursor(name)
            start = datetime.fromisoformat(cursor) if cursor else self._origin
            if end <= start:
                continue
            found.extend(self.policy.process(sid, self.store.hourly_usage(sid, start, end)))
            last = self.policy.flush(sid)
            if last is not None:
                found.append(last)
            self.store.set_cursor(name, end.isoformat())
        if not found:
            return 0
        self.store.insert_anomalies(found)
        by_window: dict[datetime, list[Anomaly]] = {}
        for a in found:
            by_window.setdefault(a.window_start, []).append(a)
        payloads = compose_alert(found, self._sensors, self.cfg.household_id)
        for p in payloads:
            self.store.log_alert(p, by_window[p.window_start])
        return len(payloads)

    def _send_unsent(self) -> None:
        for la in self.store.unsent_alerts():
            try:
                remote = deliver(la.payload, self.supabase, self.apprise)
            except SinkError as e:
                log.warning("alert delivery failed, retry next tick: %s", e)
                return
            self.store.mark_sent(la.id, remote or la.id)

    def _apply_feedback(self) -> int:
        if self.supabase is not None:
            raw = self.store.get_cursor(FEEDBACK_CURSOR)
            since = datetime.fromisoformat(raw) if raw else None
            try:
                rows = self.supabase.fetch_feedback(self.cfg.household_id, since)
            except SinkError as e:
                log.warning("feedback poll failed, retry next tick: %s", e)
                rows = []
            if rows:
                self.store.upsert_feedback(rows)
                newest = max(r.created_at for r in rows).astimezone(TZ)
                self.store.set_cursor(FEEDBACK_CURSOR, newest.isoformat())
        alerts = self._alert_ids()
        applied = 0
        for f in self.store.unapplied_feedback():
            if f.alert_id is None:  # e.g. "missed" with only a day: nothing to learn
                self.store.mark_applied(f.id)
                continue
            local = alerts.get(f.alert_id)
            if local is None:
                log.info("feedback %s refers to unknown alert %s", f.id, f.alert_id)
                continue
            for a in self.store.anomalies_for_alert(local):
                key = (a.sensor_id, a.window_start.astimezone(TZ))
                before = self._mean(a)
                self.policy.apply_feedback(a, f.verdict)
                self.feedback_log.append({
                    "feedback_id": f.id, "alert_id": f.alert_id, "verdict": f.verdict,
                    "sensor_id": key[0], "window_start": key[1].isoformat(),
                    "mean_before": before, "mean_after": self._mean(a)})
            self.store.mark_applied(f.id)
            applied += 1
        return applied

    def _mean(self, a: Anomaly) -> float:
        ws = a.window_start.astimezone(TZ)
        return self.policy.learned_mean(a.sensor_id, day_type(ws), window_of(ws))

    def _daily(self, now: datetime) -> bool:
        day = now.date() if now.hour >= self.cfg.detector.daily_report_hour \
            else now.date() - timedelta(days=1)
        if day < self._origin.date() or self.store.get_cursor(_daily_cursor(day)) is not None:
            return False
        lo, hi = _midnight(day), _midnight(day + timedelta(days=1))
        usage = {sid: self.store.hourly_usage(sid, lo, hi) for sid in self._sensors}
        count = sum(1 for la in self.store.list_alert_log()
                    if la.payload.kind == "anomaly"
                    and la.payload.window_start.astimezone(TZ).date() == day)
        payload = compose_daily(day, usage, self._sensors, self.cfg.household_id, count)
        try:
            deliver(payload, self.supabase, self.apprise)
        except SinkError as e:
            log.warning("daily report delivery failed, retry next tick: %s", e)
            return False
        self.store.set_cursor(_daily_cursor(day), now.isoformat())
        return True

    # -- loop ----------------------------------------------------------------------------------

    def stop(self, *_: object) -> None:
        self._stop = True

    def _report(self, r: TickResult) -> None:
        st = self.ingester.stats if self.ingester is not None else None
        print(f"TICK readings={r.readings} alerts={r.alerts} feedback={r.feedback_applied}"
              f" daily={int(r.daily_sent)} received={st.received if st else 0}"
              f" dropped={st.dropped if st else 0} stored={st.stored if st else 0}", flush=True)

    def run(self, once: bool, idle_seconds: float) -> int:
        if self.ingester is not None:
            try:
                self.ingester.connect(timeout=self.connect_timeout)
            except BrokerUnreachable as e:
                print(f"broker unreachable: {e}", file=sys.stderr)
                return EXIT_BROKER
            self.ingester.start()
        try:
            if once:
                # Drain the broker queue first so a 5-minute slot is not split across flushes.
                while self.ingester is not None and self.ingester.idle_for() < idle_seconds:
                    time.sleep(0.1)
                self._report(self.tick())
                return EXIT_OK
            while not self._stop:
                self._report(self.tick())
                deadline = time.monotonic() + self.cfg.detector.tick_seconds
                while not self._stop and time.monotonic() < deadline:
                    time.sleep(0.5)
            return EXIT_OK
        finally:
            if self.ingester is not None:
                self.ingester.stop()
                self.ingester.flush()

    def write_json(self, path: str) -> None:
        first = self.feedback_log[0] if self.feedback_log else {}
        data = {"mean_before": first.get("mean_before"), "mean_after": first.get("mean_after"),
                "feedback": self.feedback_log,
                "tick": asdict(self.last) if self.last is not None else None,
                "stats": asdict(self.ingester.stats) if self.ingester is not None else None}
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="solowatch daemon", description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True)
    ap.add_argument("--once", action="store_true", help="drain the broker, tick once, exit")
    ap.add_argument("--now", default=None, help="fixed clock, ISO 8601 with offset")
    ap.add_argument("--idle-seconds", type=float, default=2.0)
    ap.add_argument("--connect-timeout", type=float, default=15.0)
    ap.add_argument("--json-out", default=None, help="write feedback means and stats as JSON")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return EXIT_CONFIG
    clock: Callable[[], datetime]
    if args.now is not None:
        try:
            fixed = datetime.fromisoformat(args.now)
        except ValueError:
            print(f"config error: --now {args.now!r} is not ISO 8601", file=sys.stderr)
            return EXIT_CONFIG
        fixed = fixed.replace(tzinfo=TZ) if fixed.tzinfo is None else fixed.astimezone(TZ)
        clock = lambda: fixed
    else:
        clock = lambda: datetime.now(TZ)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if cfg.store_path != ":memory:":
        Path(cfg.store_path).parent.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(cfg.store_path)
    try:
        policy = HomePolicy(cfg.sensors, learn_until(cfg, store, clock().date()),
                            cfg.detector.threshold)
        ingester = Ingester(cfg, store)
        supabase = SupabaseSink(cfg.supabase) if cfg.supabase is not None else None
        d = Daemon(cfg, store, policy, ingester, supabase, AppriseSink(cfg.apprise_urls), clock)
        d.connect_timeout = args.connect_timeout
        signal.signal(signal.SIGTERM, d.stop)
        code = d.run(once=args.once, idle_seconds=args.idle_seconds)
        if args.json_out and code == EXIT_OK:
            d.write_json(args.json_out)
        return code
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
