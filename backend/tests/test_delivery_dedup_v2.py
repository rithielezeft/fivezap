"""Tests for body_hash dedup + send pacer (delivery_queue) and the new
groups/channels endpoints wiring.

Bug reported by user (2026-02-28): "duplicação rápida de todas notificações
e o disparo rapido da fila de vencimento e vencendo, também precisa ter um
tempo entre cada disparo".

Fixes:
1. body_hash dedup — same rendered body to same phone within N minutes is
   collapsed even if event_key differs.
2. send_min_gap_seconds — global lock enforces N-second gap between sends.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "dq.db")
    import importlib, database
    importlib.reload(database)
    from services import delivery_queue
    importlib.reload(delivery_queue)
    return database, delivery_queue


def _run(coro):
    return asyncio.run(coro)


# ---------- body_hash dedup ----------

def test_hash_body_stable_and_normalized():
    from services.delivery_queue import _hash_body
    # Same body → same hash
    h1 = _hash_body("5511999", "Olá João, seu plano vence amanhã!", None)
    h2 = _hash_body("5511999", "Olá João, seu plano vence amanhã!", None)
    assert h1 == h2
    # Different phone → different hash
    h3 = _hash_body("5511888", "Olá João, seu plano vence amanhã!", None)
    assert h1 != h3
    # Different body → different hash
    h4 = _hash_body("5511999", "Diferente!", None)
    assert h1 != h4
    # Different image → different hash
    h5 = _hash_body("5511999", "Olá João, seu plano vence amanhã!", "/a.png")
    assert h1 != h5


def test_dedup_by_body_hash_across_event_keys(tmp_path, monkeypatch):
    """CRITICAL: two callers with DIFFERENT event_keys but same rendered body
    to same phone → only ONE actual send. This was the missing safety net."""
    database, dq = _fresh_env(tmp_path)

    send_calls = []
    async def fake_send(phone, body, image_url=None, typing_ms=0):
        send_calls.append({"phone": phone, "body": body})
        return {"success": True}
    monkeypatch.setattr("services.whatsapp_client.send_message", fake_send)
    # Enable body_hash dedup by setting the window to 15
    async def go():
        await database.init_db()
        await database.set_setting("body_dedup_window_minutes", "15")
        # First delivery — event_key A
        await dq.enqueue("expiration_3d", "5511999", "Seu plano vence em 3 dias! Renove.")
        # Second delivery — DIFFERENT event_key, SAME body → must dedupe
        await dq.enqueue("bulk_expired_notify", "5511999", "Seu plano vence em 3 dias! Renove.")

    _run(go())
    assert len(send_calls) == 1, (
        f"Expected 1 send (2nd dedup'd by body_hash), got {len(send_calls)}: {send_calls}"
    )


def test_dedup_body_hash_disabled_when_window_zero(tmp_path, monkeypatch):
    """Setting body_dedup_window_minutes=0 turns the second net OFF."""
    database, dq = _fresh_env(tmp_path)

    send_calls = []
    async def fake_send(phone, body, image_url=None, typing_ms=0):
        send_calls.append(1)
        return {"success": True}
    monkeypatch.setattr("services.whatsapp_client.send_message", fake_send)

    async def go():
        await database.init_db()
        await database.set_setting("body_dedup_window_minutes", "0")
        # Also disable phone+event dedup so we measure ONLY body_hash
        await database.set_setting("dedup_enabled", "false")
        await dq.enqueue("event_a", "5511999", "same body")
        await dq.enqueue("event_b", "5511999", "same body")

    _run(go())
    # Without any dedup, both fire
    assert len(send_calls) == 2


# ---------- send pacer ----------

def test_wait_for_pace_slot_enforces_min_gap(tmp_path):
    """When send_min_gap_seconds=1, two sequential _wait_for_pace_slot calls
    take at least ~1 second combined."""
    database, dq = _fresh_env(tmp_path)
    import time

    async def go():
        await database.init_db()
        await database.set_setting("send_min_gap_seconds", "0.5")
        t0 = time.monotonic()
        await dq._wait_for_pace_slot()  # first — no wait
        await dq._wait_for_pace_slot()  # second — must wait ~0.5s
        await dq._wait_for_pace_slot()  # third — must wait another ~0.5s
        return time.monotonic() - t0

    elapsed = _run(go())
    # 2 gaps of 0.5s each = ~1.0s minimum
    assert elapsed >= 0.9, f"expected >=0.9s (2 gaps of 0.5s), got {elapsed:.2f}s"
    # Tolerance upper bound so we know it's not stalling
    assert elapsed < 3.0, f"pacer overshoot: {elapsed:.2f}s"


def test_wait_for_pace_slot_no_wait_when_gap_zero(tmp_path):
    database, dq = _fresh_env(tmp_path)
    import time

    async def go():
        await database.init_db()
        await database.set_setting("send_min_gap_seconds", "0")
        t0 = time.monotonic()
        for _ in range(5):
            await dq._wait_for_pace_slot()
        return time.monotonic() - t0

    elapsed = _run(go())
    assert elapsed < 0.2, f"gap=0 should be instant, took {elapsed:.2f}s"
