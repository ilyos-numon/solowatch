"""Virtual home demo: reset -> inject -> Supabase -> family feedback -> re-inject; demo page shots."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import (
    DEMO_HID,
    FAMILY_USER_ID,
    ROOT,
    DemoServer,
    admin_client,
    clean_supabase,
    family_client,
    wait_for,
)

SENTENCE = "이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다"
SHOT = r"""
const { chromium } = require(process.argv[2]);
(async () => {
  const [, , , url, out, mode] = process.argv;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 },
                                       timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
  await page.goto(url);
  await page.getByTestId('demo-page').waitFor({ timeout: 30000 });
  await page.getByTestId('demo-not-ready').waitFor({ state: 'detached', timeout: 60000 });
  if (mode === 'after') {
    await page.getByTestId('demo-score-row').first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: out, fullPage: true });
    await page.getByTestId('tab-family').click();
    await page.getByTestId('alert-item').filter({ hasText: '11/2 06:00' }).first()
      .waitFor({ timeout: 30000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: out.replace(/\.png$/, '-family.png'), fullPage: true });
  } else {
    await page.getByTestId('btn-inject-no_morning_water').waitFor({ timeout: 30000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: out, fullPage: true });
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def shot_dir() -> Path:
    d = Path(os.environ.get("ILLY_SHOT_DIR", "tests/e2e/screenshots"))
    d = d if d.is_absolute() else ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def screenshot(demo: DemoServer, tmp: Path, name: str, mode: str) -> None:
    script = tmp / "shot.cjs"
    script.write_text(SHOT, encoding="utf-8")
    pw = ROOT / "web/node_modules/@playwright/test"
    out = shot_dir() / name
    cmd = (f'source ~/.nvm/nvm.sh >/dev/null 2>&1; node "{script}" "{pw}" "{demo.base}/demo" '
           f'"{out}" {mode}')
    r = subprocess.run(["bash", "-c", cmd], check=False, cwd=ROOT, capture_output=True,
                       text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-800:]
    assert out.is_file()


@pytest.fixture(scope="module", autouse=True)
def _cleanup_remote() -> Iterator[None]:
    clean_supabase()
    yield
    clean_supabase()


@pytest.fixture
def home(demo_server: DemoServer) -> DemoServer:
    """The demo server freshly reset (day_index 0)."""
    clean_supabase()
    r = demo_server.post("/api/demo/reset", timeout=120)
    assert r.status_code == 200, r.text
    assert r.json()["ready"] is True
    return demo_server


def inject(demo: DemoServer, kind: str) -> dict[str, Any]:
    r = demo.post("/api/demo/inject", {"kind": kind})
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


def score(entries: list[dict[str, Any]], sensor: str, window: str) -> float:
    (e,) = [e for e in entries if e["sensor_id"] == sensor and e["window"] == window]
    return float(e["score"])


def test_reset_seeds_history(home: DemoServer) -> None:
    state = home.get("/api/demo/state").json()
    assert state["ready"] is True
    assert state["readings_total"] == 32256
    assert state["day_index"] == 0
    db = admin_client()
    anomalies = db.table("alerts").select("window_start").eq("household_id", DEMO_HID).eq(
        "kind", "anomaly").execute().data
    assert len(anomalies) >= 7, anomalies
    away_days = db.table("alerts").select("id").eq("household_id", DEMO_HID).eq(
        "kind", "anomaly").gte("window_start", "2026-10-26T00:00:00+09:00").lt(
        "window_start", "2026-10-28T00:00:00+09:00").execute().data
    assert away_days == []
    away = db.table("away_periods").select("id").eq("household_id", DEMO_HID).eq(
        "note", "demo-seed").execute().data
    assert len(away) == 1


def test_inject_morning_water(home: DemoServer) -> None:
    t0 = time.monotonic()
    data = inject(home, "no_morning_water")
    assert time.monotonic() - t0 <= 10
    assert SENTENCE in [a["sentence"] for a in data["alerts"]], data["alerts"]
    assert data["day"] == "2026-11-02"
    assert data["readings"] == 1152
    assert data["daily_sent"] is True
    rows = admin_client().table("alerts").select("id").eq("household_id", DEMO_HID).eq(
        "sentence", SENTENCE).gte("window_start", "2026-11-02T00:00:00+09:00").lt(
        "window_start", "2026-11-03T00:00:00+09:00").execute().data
    assert rows, "alert not in Supabase"


def test_feedback_lowers_score(home: DemoServer, tmp_path: Path) -> None:
    screenshot(home, tmp_path, "demo-live-before.png", "before")
    first = inject(home, "no_morning_water")
    alert = next(a for a in first["alerts"] if a["sentence"] == SENTENCE)
    family_client().table("alert_feedback").insert({
        "alert_id": alert["remote_id"], "household_id": DEMO_HID, "user_id": FAMILY_USER_ID,
        "verdict": "ok", "day": first["day"]}).execute()

    def synced() -> bool:
        outbox = home.get("/api/demo/state").json()["outbox"]
        return any(o["direction"] == "in" and o["table"] == "alert_feedback" for o in outbox)

    assert wait_for(synced, 20, 1.0), "feedback was not pulled into the home"
    second = inject(home, "no_morning_water")
    assert second["previous_scores"], "no previous scores"
    after = score(second["scores"], "water_main", "morning")
    before = score(second["previous_scores"], "water_main", "morning")
    assert after < before, (after, before)
    screenshot(home, tmp_path, "demo-live-after.png", "after")


def test_normal_day_quiet(home: DemoServer) -> None:
    data = inject(home, "normal")
    assert data["alerts"] == []
    assert data["daily_sent"] is True


def test_auto_reset_and_bad_kind(home: DemoServer) -> None:
    for i in range(14):   # an ordinary day never raises a false alarm, 14 days in a row
        data = inject(home, "normal")
        assert data["alerts"] == [], (i, data["alerts"])
        assert data["auto_reset"] is False
    state = home.get("/api/demo/state").json()
    assert state["day_index"] == 14
    data = inject(home, "normal")
    assert data["auto_reset"] is True
    assert home.get("/api/demo/state").json()["day_index"] == 1
    bad = home.post("/api/demo/inject", {"kind": "x"})
    assert bad.status_code == 400
    assert bad.json()["error"] == "unknown_kind"
