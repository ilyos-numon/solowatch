"""Alert insert -> DB webhook -> Edge Function -> web-push to a fake push service."""
from __future__ import annotations

import base64
import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import (
    DEMO_HID,
    FAMILY_USER_ID,
    PushReceiver,
    admin_client,
    clean_supabase,
    wait_for,
)

ENDPOINT = "http://host.docker.internal:8843/push"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture
def subscription(functions_serve: None) -> Iterator[None]:
    """A family push subscription whose endpoint is the local fake push service."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    point = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    db = admin_client()
    clean_supabase()
    db.table("push_subscriptions").delete().eq("endpoint", ENDPOINT).execute()
    db.table("push_subscriptions").insert({
        "household_id": DEMO_HID, "user_id": FAMILY_USER_ID, "endpoint": ENDPOINT,
        "p256dh": _b64url(point), "auth": _b64url(os.urandom(16))}).execute()
    yield
    db.table("push_subscriptions").delete().eq("endpoint", ENDPOINT).execute()
    clean_supabase()


def _insert_alert(kind: str) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    admin_client().table("alerts").insert({
        "household_id": DEMO_HID, "kind": kind, "window_start": now.isoformat(),
        "window_end": now.isoformat(),
        "sentence": "이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다"
        if kind == "anomaly" else "오늘은 평소와 같았습니다"}).execute()


def test_anomaly_alert_reaches_push_service(subscription: None,
                                            push_receiver: PushReceiver) -> None:
    _insert_alert("anomaly")
    assert wait_for(lambda: push_receiver.count() >= 1, 15, 0.5), "no push within 15s"
    records = push_receiver.records()
    assert len(records) == 1, records
    headers = records[0]["headers"]
    assert headers["authorization"].startswith("vapid "), headers
    assert "ttl" in headers, headers
    assert records[0]["length"] > 0


def test_daily_ok_alert_sends_no_push(subscription: None, push_receiver: PushReceiver) -> None:
    _insert_alert("daily_ok")
    assert not wait_for(lambda: push_receiver.count() > 0, 10, 0.5), push_receiver.records()
