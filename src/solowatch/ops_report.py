"""`ops-report`: 4주 운영 기록 표 (docs/vision.md) 를 기기 저장소에서 만든다.

알림 로그(`alerts_log`)와 가족 판단(`feedback`), 시뮬레이션이면 주입 이벤트를 날짜별로 합친다.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

from solowatch.alerts import ALERT_PREFIX, ALERT_SUFFIX, SEP
from solowatch.contracts import TZ
from solowatch.contracts_mvp import DEFAULT_HOME, FeedbackRow, HomeScenario, LoggedAlert
from solowatch.store import SqliteStore

SCENARIOS: dict[str, HomeScenario] = {"default": DEFAULT_HOME}
VERDICT_KO = {"ok": "괜찮았음", "checking": "확인 중", "confirmed": "실제 이상", "missed": "놓친 경보"}
CLASS_BY_VERDICT = {"ok": "오경보", "confirmed": "실제 이상"}
UNREVIEWED = "미확인"
MISSED = "놓친 경보"
EVENT_KO = {"no_morning_water": "아침 물 사용 없음", "no_usage_all_day": "하루 종일 사용 없음",
            "night_flow": "밤새 물 흐름", "light_all_night": "거실등 밤새 켜짐",
            "no_tv_evening": "저녁 TV 사용 없음", "fridge_off": "냉장고 전원 꺼짐",
            "different_morning": "평소와 다른 아침"}


def _alert_day(a: LoggedAlert) -> date:
    return a.payload.window_start.astimezone(TZ).date()


def _core(sentence: str) -> str:
    parts = sentence.split(SEP)
    if parts and parts[0] == ALERT_PREFIX:
        parts = parts[1:]
    if parts and parts[-1] == ALERT_SUFFIX:
        parts = parts[:-1]
    return SEP.join(parts)


def _judgement(f: FeedbackRow | None) -> str:
    if f is None:
        return "-"
    label = VERDICT_KO.get(f.verdict, f.verdict)
    return f"{label} ({f.note})" if f.note else label


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def build_report(store: SqliteStore, scenario: HomeScenario | None) -> tuple[str, dict[str, Any]]:
    alerts = [a for a in store.list_alert_log() if a.payload.kind == "anomaly"]
    feedback = store.list_feedback()  # ordered by created_at → the last answer wins
    by_alert: dict[str, FeedbackRow] = {}
    missed_notes: dict[date, str] = {}
    for fb in feedback:
        if fb.alert_id is not None:
            by_alert[fb.alert_id] = fb
        elif fb.verdict == "missed" and fb.day is not None:
            missed_notes[fb.day] = fb.note or VERDICT_KO["missed"]

    days: dict[date, list[tuple[str, str, str]]] = {}
    counts = {"오경보": 0, "실제 이상": 0, UNREVIEWED: 0}
    for a in alerts:
        f = by_alert.get(a.id) or (by_alert.get(a.remote_id) if a.remote_id else None)
        cls = CLASS_BY_VERDICT.get(f.verdict, UNREVIEWED) if f is not None else UNREVIEWED
        counts[cls] += 1
        days.setdefault(_alert_day(a), []).append((_core(a.payload.sentence), _judgement(f), cls))

    alert_days = set(days)
    missed: dict[date, str] = {d: n for d, n in missed_notes.items() if d not in alert_days}
    if scenario is not None:
        for e in scenario.events:
            if e.day not in alert_days and e.day not in missed:
                missed[e.day] = f"(모의) {EVENT_KO.get(e.kind, e.kind)}"

    away = list(store.list_away()) + (list(scenario.away_periods()) if scenario else [])
    away_silent = not any(p.start_date <= d <= p.end_date for d in alert_days for p in away)

    lines: list[str] = []
    if scenario is not None:
        header = (f"> 모의 데이터 — 시나리오 `{scenario.slug}` {scenario.start.isoformat()}부터 "
                  f"{scenario.days}일 (학습 {scenario.learn_days}일). 실제 가정 기록이 아니다.")
        lines += [header, ""]
    lines += ["# 4주 운영 기록", "", "| 날짜 | 알림 | 가족 판단 | 분류 |", "|---|---|---|---|"]
    for d in sorted(alert_days | set(missed)):
        label = f"{d.month:02d}/{d.day:02d}"
        if d in days:
            rows = days[d]
            alert_text = f"이상 가능성 {len(rows)}건: " + "; ".join(r[0] for r in rows)
            judged = "; ".join(dict.fromkeys(r[1] for r in rows))
            classes = list(dict.fromkeys(r[2] for r in rows))
            lines.append(f"| {label} | {_cell(alert_text)} | {_cell(judged)} | "
                         f"{' · '.join(classes)} |")
        else:
            lines.append(f"| {label} | 없음 | {_cell(missed[d])} | {MISSED} |")
    lines.append(f"| 합계 | 알림 {len(alerts)}건 | | 오경보 {counts['오경보']}건 · "
                 f"놓친 경보 {len(missed)}건 |")
    metrics: dict[str, Any] = {
        "alerts": len(alerts), "false_alarms": counts["오경보"], "missed": len(missed),
        "confirmed": counts["실제 이상"], "unreviewed": counts[UNREVIEWED],
        "away_days_silent": away_silent,
    }
    return "\n".join(lines) + "\n", metrics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solowatch ops-report",
                                     description="alerts_log + feedback -> 운영 기록 Markdown 표")
    parser.add_argument("--db", required=True, help="device SQLite path (must exist)")
    parser.add_argument("--out", required=True, help="Markdown output path")
    parser.add_argument("--json", default=None, help="metrics JSON output path")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default=None,
                        help="simulated run: also count injected event days without alert")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    if not Path(args.db).is_file():
        print(f"solowatch ops-report: db not found: {args.db}", file=sys.stderr)
        return 2
    try:
        store = SqliteStore(args.db)
        try:
            md, metrics = build_report(store, SCENARIOS[args.scenario] if args.scenario else None)
        finally:
            store.close()
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    except (OSError, sqlite3.Error) as e:
        print(f"solowatch ops-report failed: {e}", file=sys.stderr)
        return 1
    print(f"OPS alerts {metrics['alerts']}, false alarms {metrics['false_alarms']}, "
          f"missed {metrics['missed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
