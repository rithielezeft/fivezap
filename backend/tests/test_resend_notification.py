"""Tests for the manual resend-notification endpoint.

This endpoint is the admin's escape hatch when auto-notification silently
failed. It must:
- Refuse to resend for non-paid payments (with a clear reason).
- Cascade phone resolution (SQLite → Mongo → painel cache).
- Try template first, fall back to hardcoded message if template disabled.
- Return a rich diagnostic showing exactly which step succeeded/failed.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "resend.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    from services import notifier
    importlib.reload(notifier)
    return database


async def _seed(database, whatsapp="5511900001111", status="paid"):
    import aiosqlite
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await database.init_db()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO customers "
            "(id, name, whatsapp, system_type, created_at, updated_at) "
            "VALUES ('cust-1', 'João', ?, 'iptv', ?, ?)",
            (whatsapp, now, now),
        )
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
            " package_id, status, order_nsu, created_at)"
            " VALUES ('pmt-1', 'cust-1', 1, 3500, 17, ?, 'renew-cust-1-1m', ?)",
            (status, now),
        )
        await db.commit()


def test_resend_when_payment_not_paid_returns_reason(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    async def go():
        await _seed(database, status="pending")
        return await payments_mod.resend_notification("pmt-1")

    result = _run(go())
    assert result["result"] == "not_sent"
    assert "pending" in result["reason"]


def test_resend_sends_via_template_when_enabled(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import whatsapp_client

    sent = []

    async def fake_wa(phone, body, image_url=None, **kw):
        sent.append({"phone": phone, "body": body})

    async def fake_status():
        return {"ready": True, "state": "connected"}

    async def go():
        await _seed(database)
        with patch.object(whatsapp_client, "send_message", new=fake_wa), \
             patch.object(whatsapp_client, "get_status", new=fake_status):
            return await payments_mod.resend_notification("pmt-1")

    result = _run(go())
    assert result["result"] == "sent"
    assert result["method"] == "template"
    assert result["resolved_phone"] == "5511900001111"
    assert len(sent) == 1


def test_resend_fallback_when_template_disabled(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import payments as payments_mod
    from services import whatsapp_client

    sent = []

    async def fake_wa(phone, body, image_url=None, **kw):
        sent.append({"phone": phone, "body": body})

    async def fake_status():
        return {"ready": True, "state": "connected"}

    async def go():
        await _seed(database)
        # Disable renewal_success template
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE notification_templates SET enabled = 0 WHERE event_key = 'renewal_success'"
            )
            await db.commit()
        with patch.object(whatsapp_client, "send_message", new=fake_wa), \
             patch.object(whatsapp_client, "get_status", new=fake_status):
            return await payments_mod.resend_notification("pmt-1")

    result = _run(go())
    assert result["result"] == "sent"
    assert result["method"] == "hardcoded_fallback"
    assert "João" in sent[0]["body"]
    assert "template" in result["note"].lower()


def test_resend_says_wa_not_ready_when_service_down(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import whatsapp_client

    async def fake_status():
        return {"ready": False, "state": "disconnected"}

    async def go():
        await _seed(database)
        with patch.object(whatsapp_client, "get_status", new=fake_status):
            return await payments_mod.resend_notification("pmt-1")

    result = _run(go())
    assert result["result"] == "not_sent"
    assert "not ready" in result["reason"]
    assert "disconnected" in result["reason"]


def test_resend_resolves_phone_from_painel_cache(tmp_path):
    """Local SQLite has empty whatsapp — must fall back to painel cache."""
    database = _fresh_env(tmp_path)
    from routers import painel_users as painel_mod
    from routers import payments as payments_mod
    from services import whatsapp_client

    async def fake_read_cache():
        return ([{
            "id": "cust-1",
            "username": "joao",
            "as_number": "5511987654321",
        }], {})

    async def fake_status():
        return {"ready": True, "state": "connected"}

    async def fake_wa(phone, body, image_url=None, **kw):
        pass

    async def go():
        await _seed(database, whatsapp="")   # empty locally
        with patch.object(painel_mod, "_read_cache", new=fake_read_cache), \
             patch.object(whatsapp_client, "send_message", new=fake_wa), \
             patch.object(whatsapp_client, "get_status", new=fake_status):
            return await payments_mod.resend_notification("pmt-1")

    result = _run(go())
    assert result["result"] == "sent"
    assert result["resolved_phone"] == "5511987654321"
    # The steps trail must show that painel_cache is where it came from
    sources = [s.get("source") for s in result["steps"]]
    assert "painel_cache" in sources


def test_resend_no_phone_anywhere_returns_reason(tmp_path):
    """Empty everywhere → clear error."""
    database = _fresh_env(tmp_path)
    from routers import painel_users as painel_mod
    from routers import payments as payments_mod
    from services import whatsapp_client

    async def empty_cache():
        return ([], {})

    async def fake_status():
        return {"ready": True, "state": "connected"}

    async def go():
        await _seed(database, whatsapp="")
        with patch.object(painel_mod, "_read_cache", new=empty_cache), \
             patch.object(whatsapp_client, "get_status", new=fake_status):
            return await payments_mod.resend_notification("pmt-1")

    result = _run(go())
    assert result["result"] == "not_sent"
    assert "no whatsapp" in result["reason"].lower()


def test_resend_returns_404_for_unknown_payment(tmp_path):
    database = _fresh_env(tmp_path)
    from fastapi import HTTPException
    from routers import payments as payments_mod

    async def go():
        await database.init_db()
        try:
            return await payments_mod.resend_notification("no-such-pmt")
        except HTTPException as e:
            return e.status_code

    assert _run(go()) == 404
