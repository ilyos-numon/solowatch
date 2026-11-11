from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from solowatch.contracts import TZ
from solowatch.contracts_mvp import (
    DEMO_HOUSEHOLD_ID,
    AlertPayload,
    AwayPeriod,
    FeedbackRow,
    HomeScenario,
    InjectedEvent,
    Verdict,
)
from solowatch.ops_report import build_report, main
from solowatch.store import SqliteStore


def _alert(store: SqliteStore, day: date, hour: int = 6, kind: str = "anomaly") -> str:
    ws = datetime.combine(day, datetime.min.time(), TZ) + timedelta(hours=hour)
    payload = AlertPayload(DEMO_HOUSEHOLD_ID, kind, ws, ws + timedelta(hours=6),  # type: ignore[arg-type]
                           f"이상 가능성 있음 · {day.isoformat()} · 평소와 다릅니다")
    return store.log_alert(payload, [])


def _feedback(store: SqliteStore, alert_id: str | None, verdict: Verdict,
              day: date | None = None, note: str = "") -> None:
    created = datetime(2026, 11, 1, 12, tzinfo=TZ)
    store.upsert_feedback([FeedbackRow(str(uuid.uuid4()), alert_id, verdict, day, note, created)])


def _totals(md: str) -> str:
    return next(line for line in md.splitlines() if "합계" in line)


def test_classifies_ok_confirmed_unreviewed_per_alert() -> None:
    store = SqliteStore(":memory:")
    a1 = _alert(store, date(2026, 10, 21))
    a2 = _alert(store, date(2026, 10, 23))
    _alert(store, date(2026, 10, 24))
    store.mark_sent(a2, "remote-2")
    _feedback(store, a1, "ok", note="불 켜 두고 잠듦")
    _feedback(store, "remote-2", "confirmed")  # family feedback references the remote id

    md, metrics = build_report(store, None)

    assert "| 날짜 | 알림 | 가족 판단 | 분류 |" in md
    assert _totals(md) == "| 합계 | 알림 3건 | | 오경보 1건 · 놓친 경보 0건 |"
    assert metrics == {"alerts": 3, "false_alarms": 1, "missed": 0, "confirmed": 1,
                       "unreviewed": 1, "away_days_silent": True}
    rows = {line.split(" | ")[0]: line for line in md.splitlines() if line.startswith("| 10/")}
    assert rows["| 10/21"].endswith("| 오경보 |")
    assert "불 켜 두고 잠듦" in rows["| 10/21"]
    assert rows["| 10/23"].endswith("| 실제 이상 |")
    assert rows["| 10/24"].endswith("| 미확인 |")


def test_latest_feedback_wins_and_daily_ok_is_not_an_alert() -> None:
    store = SqliteStore(":memory:")
    a1 = _alert(store, date(2026, 10, 21))
    _alert(store, date(2026, 10, 22), kind="daily_ok")
    store.upsert_feedback([
        FeedbackRow("f1", a1, "confirmed", None, "", datetime(2026, 10, 21, 9, tzinfo=TZ)),
        FeedbackRow("f2", a1, "ok", None, "", datetime(2026, 10, 21, 10, tzinfo=TZ)),
    ])
    _, metrics = build_report(store, None)
    assert metrics["alerts"] == 1
    assert metrics["false_alarms"] == 1
    assert metrics["confirmed"] == 0


def test_missed_feedback_counts_only_on_days_without_alert() -> None:
    store = SqliteStore(":memory:")
    _alert(store, date(2026, 10, 21))
    _feedback(store, None, "missed", day=date(2026, 10, 21))
    _feedback(store, None, "missed", day=date(2026, 10, 28), note="감기로 종일 누움")

    md, metrics = build_report(store, None)

    assert metrics["missed"] == 1
    missed_row = next(line for line in md.splitlines() if line.startswith("| 10/28"))
    assert missed_row == "| 10/28 | 없음 | 감기로 종일 누움 | 놓친 경보 |"
    assert _totals(md).endswith("놓친 경보 1건 |")


def test_scenario_event_day_without_alert_is_missed_and_marks_sample() -> None:
    store = SqliteStore(":memory:")
    _alert(store, date(2026, 10, 21))
    scenario = HomeScenario(DEMO_HOUSEHOLD_ID, "home-demo", date(2026, 10, 5), 28, 1, 14,
                            events=(InjectedEvent("light_all_night", date(2026, 10, 21)),
                                    InjectedEvent("fridge_off", date(2026, 10, 29))))

    md, metrics = build_report(store, scenario)

    assert md.splitlines()[0].startswith("> 모의 데이터")
    assert metrics["missed"] == 1
    assert any(line.startswith("| 10/29 | 없음 |") and line.endswith("| 놓친 경보 |")
               for line in md.splitlines())


def test_away_days_silent_flag() -> None:
    store = SqliteStore(":memory:")
    _alert(store, date(2026, 10, 21))
    store.replace_away([AwayPeriod(date(2026, 10, 26), date(2026, 10, 27), "외출")])
    assert build_report(store, None)[1]["away_days_silent"] is True
    _alert(store, date(2026, 10, 27))
    assert build_report(store, None)[1]["away_days_silent"] is False


def test_main_writes_markdown_and_json(tmp_path: Path) -> None:
    db = tmp_path / "home.sqlite"
    store = SqliteStore(str(db))
    a1 = _alert(store, date(2026, 10, 21))
    _feedback(store, a1, "ok")
    store.close()
    out, js = tmp_path / "ops.md", tmp_path / "ops.json"

    assert main(["--db", str(db), "--out", str(out), "--json", str(js)]) == 0

    assert "| 합계 | 알림 1건 | | 오경보 1건 · 놓친 경보 0건 |" in out.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["false_alarms"] == 1


def test_main_rejects_missing_db_and_bad_args(tmp_path: Path) -> None:
    assert main(["--db", str(tmp_path / "nope.sqlite"), "--out", str(tmp_path / "o.md")]) == 2
    assert main(["--out", str(tmp_path / "o.md")]) == 2
    assert not (tmp_path / "o.md").exists()
