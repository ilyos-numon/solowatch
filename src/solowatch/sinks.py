"""알림 전송. Supabase 행 쓰기는 supabase-py, 푸시는 apprise 만 쓴다.
나가는 것은 AlertPayload / DailyReportPayload 의 to_row() 와 문장뿐이다."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

import apprise
from supabase import Client, create_client

from solowatch.contracts_mvp import (
    AlertPayload,
    AwayPeriod,
    DailyReportPayload,
    FeedbackRow,
    SupabaseConfig,
)

log = logging.getLogger(__name__)

APPRISE_TITLE = "홀로안심"


class SinkError(RuntimeError):
    """Supabase 전송·조회 실패. 재시도는 호출자(데몬)가 정한다."""


class SupabaseSink:
    def __init__(self, cfg: SupabaseConfig) -> None:
        self._cfg = cfg
        self._client: Client | None = None

    def _db(self) -> Client:
        if self._client is None:
            try:
                client = create_client(self._cfg.url, self._cfg.anon_key)
                client.auth.sign_in_with_password(
                    {"email": self._cfg.device_email, "password": self._cfg.device_password})
            except Exception as e:  # supabase-py 는 auth/httpx 예외를 그대로 올린다
                raise SinkError(f"supabase sign-in failed: {e}") from e
            self._client = client
        return self._client

    def _execute(self, what: str, build: Any) -> list[dict[str, Any]]:
        db = self._db()
        try:
            data = build(db).execute().data
        except Exception as e:
            raise SinkError(f"supabase {what} failed: {e}") from e
        return list(data or [])

    def send_alert(self, p: AlertPayload) -> str:
        rows = self._execute("insert alerts", lambda db: db.table("alerts").insert(p.to_row()))
        if not rows:
            raise SinkError("supabase insert alerts returned no row")
        return str(rows[0]["id"])

    def send_daily(self, p: DailyReportPayload) -> str:
        rows = self._execute("upsert daily_reports", lambda db: db.table("daily_reports")
                             .upsert(p.to_row(), on_conflict="household_id,day"))
        if not rows:
            raise SinkError("supabase upsert daily_reports returned no row")
        return str(rows[0]["id"])

    def fetch_feedback(self, household_id: str, since: datetime | None) -> list[FeedbackRow]:
        def build(db: Client) -> Any:
            q = db.table("alert_feedback").select("*").eq("household_id", household_id)
            if since is not None:
                q = q.gt("created_at", since.isoformat())
            return q.order("created_at", desc=False)

        rows = self._execute("select alert_feedback", build)
        return [FeedbackRow(id=str(r["id"]), alert_id=r.get("alert_id"), verdict=r["verdict"],
                            day=date.fromisoformat(r["day"]) if r.get("day") else None,
                            note=r.get("note") or "",
                            created_at=datetime.fromisoformat(r["created_at"]))
                for r in rows]

    def fetch_away(self, household_id: str) -> list[AwayPeriod]:
        rows = self._execute("select away_periods", lambda db: db.table("away_periods")
                             .select("*").eq("household_id", household_id))
        return [AwayPeriod(start_date=date.fromisoformat(r["start_date"]),
                           end_date=date.fromisoformat(r["end_date"]),
                           note=r.get("note") or "", id=str(r["id"]))
                for r in rows]


class AppriseSink:
    def __init__(self, urls: Iterable[str]) -> None:
        self._urls = tuple(u.strip() for u in urls if u.strip())

    def send(self, sentence: str) -> bool:
        if not self._urls:
            return True
        ap = apprise.Apprise()
        ap.add(list(self._urls))
        ok = bool(ap.notify(body=sentence, title=APPRISE_TITLE))  # 네트워크 오류는 apprise 가 삼킨다
        if not ok:
            log.warning("apprise delivery failed for %d url(s)", len(self._urls))
        return ok


def deliver(payload: AlertPayload | DailyReportPayload, supabase: SupabaseSink | None,
            apprise: AppriseSink) -> str | None:
    """Supabase 먼저(실패 시 SinkError 전파, 푸시 안 함), 그다음 Apprise(실패는 경고만)."""
    remote_id: str | None = None
    if supabase is not None:
        if isinstance(payload, AlertPayload):
            remote_id = supabase.send_alert(payload)
        else:
            remote_id = supabase.send_daily(payload)
    apprise.send(payload.sentence)
    return remote_id
