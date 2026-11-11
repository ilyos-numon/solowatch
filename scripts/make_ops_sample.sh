#!/usr/bin/env bash
# docs/ops-sample.md 재생성: 모의 가정 28일 → HomePolicy 재생 → 알림 로그 → 모의 가족 판단 → ops-report.
# 판단 규칙 (PLAN S11): 10-21·10-25 알림은 "ok"(괜찮았음), 나머지는 "confirmed"(실제 이상).
set -euo pipefail
cd "$(dirname "$0")/.."

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
db="$work/home.sqlite"

SOLOWATCH_SAMPLE_DB="$db" uv run python - <<'PY'
import os
import uuid
from datetime import date, datetime

from solowatch.alerts import compose_alert
from solowatch.contracts import TZ
from solowatch.contracts_mvp import DEFAULT_HOME, FeedbackRow
from solowatch.policy import HomePolicy
from solowatch.simulate_home import simulate_home
from solowatch.store import SqliteStore

OK_DAYS = {date(2026, 10, 21), date(2026, 10, 25)}
home = DEFAULT_HOME
store = SqliteStore(os.environ["SOLOWATCH_SAMPLE_DB"])
for readings in simulate_home(home).values():
    store.insert_readings(readings)
store.replace_away(home.away_periods())

policy = HomePolicy(home.sensors, home.learn_until)
policy.set_away(store.list_away())
anomalies = []
for spec in home.sensors:
    anomalies += policy.process(spec.sensor_id,
                                store.hourly_usage(spec.sensor_id, home.start_dt, home.end_dt))
    last = policy.flush(spec.sensor_id)
    if last is not None:
        anomalies.append(last)

sensors = {s.sensor_id: s for s in home.sensors}
feedback = []
for payload in compose_alert(anomalies, sensors, home.household_id):
    group = [a for a in anomalies if a.window_start == payload.window_start]
    alert_id = store.log_alert(payload, group)
    day = payload.window_start.astimezone(TZ).date()
    verdict = "ok" if day in OK_DAYS else "confirmed"
    created = datetime.combine(day, datetime.min.time(), TZ).replace(hour=21)
    feedback.append(FeedbackRow(str(uuid.uuid4()), alert_id, verdict, day, "", created))
store.upsert_feedback(feedback)
store.close()
print(f"replayed {home.days} days: {len(feedback)} alerts logged")
PY

uv run python -m solowatch.ops_report --db "$db" --out docs/ops-sample.md --scenario default
