"""Tests for admin payment alerts.

When a customer pays, the owner/admin must be notified on WhatsApp so they
know the money came in — even if the client-side notification fails or the
painel.fun renewal errors out.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "admin_alerts.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    from services import notifier
    importlib.reload(notifier)
    return database


# ---------- send_admin_alert helper ----------

def test_send_admin_alert_skips_when_setting_empty(tmp_path):
    database = _fresh_env(tmp_path)
    from services import notifier, whatsapp_client

    sent = []

    async def fake_send(phone, body, image_url=None, **kw):
        sent.append((phone, body))

    async def go():
        await database.init_db()
        with patch.object(whatsapp_client, "send_message", new=fake_send):
            return await notifier.send_admin_alert("hi")

    assert _run(go()) is False
    assert sent == []


def test_send_admin_alert_sends_to_configured_phone(tmp_path):
    database = _fresh_env(tmp_path)
    from services import notifier, whatsapp_client

    sent = []

    async def fake_send(phone, body, image_url=None, **kw):
        sent.append((phone, body))

    async def go():
        await database.init_db()
        await database.set_setting("admin_whatsapp", "5511999998888")
        with patch.object(whatsapp_client, "send_message", new=fake_send):
            return await notifier.send_admin_alert("💰 pagamento X")

    assert _run(go()) is True
    assert sent == [("5511999998888", "💰 pagamento X")]


def test_send_admin_alert_survives_whatsapp_failure(tmp_path):
    """WhatsApp client raising must NOT bubble up — admin alerts are best-effort."""
    database = _fresh_env(tmp_path)
    from services import notifier, whatsapp_client

    async def bad_send(phone, body, image_url=None, **kw):
        raise RuntimeError("wa-service down")

    async def go():
        await database.init_db()
        await database.set_setting("admin_whatsapp", "5511999998888")
        with patch.object(whatsapp_client, "send_message", new=bad_send):
            return await notifier.send_admin_alert("teste")

    assert _run(go()) is False


# ---------- _process_payment_confirmation triggers admin alert ----------

def test_admin_alert_fires_on_successful_renewal(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from datetime import datetime, timezone
    from routers import payments as payments_mod
    from services import notifier, painel, whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_msgs = []
    client_msgs = []

    async def fake_wa_send(phone, body, image_url=None, **kw):
        # admin_whatsapp is 5511777777777, customer is 5511888888888
        if phone == "5511777777777":
            admin_msgs.append(body)
        else:
            client_msgs.append((phone, body))

    async def fake_renew(user_id, package_id):
        return {"expires_at": "2027-01-01"}

    async def go():
        await database.init_db()
        await database.set_setting("admin_whatsapp", "5511777777777")
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("228116806", "João Cliente", "5511888888888", "iptv", now_iso, now_iso),
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("p-ok", "228116806", 3, 9000, 43, "pending",
                 "renew-228116806-3m", now_iso),
            )
            await db.commit()

        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa_send):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-3m", paid=True, source="webhook", raw={"paid": True},
            )

    result = _run(go())
    assert result["status"] == "renewed"
    # Admin was alerted (exactly one message)
    assert len(admin_msgs) == 1
    body = admin_msgs[0]
    assert "Pagamento confirmado" in body
    assert "João Cliente" in body
    assert "3 mês(es)" in body
    assert "R$ 90,00" in body
    assert "IPTV" in body


def test_admin_alert_fires_when_painel_id_missing(tmp_path):
    """Customer paid but no painel_id → admin must be told to renew manually."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from datetime import datetime, timezone
    from routers import payments as payments_mod
    from services import whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_msgs = []

    async def fake_wa_send(phone, body, image_url=None, **kw):
        if phone == "5511777777777":
            admin_msgs.append(body)

    async def go():
        await database.init_db()
        await database.set_setting("admin_whatsapp", "5511777777777")
        async with aiosqlite.connect(database.DB_PATH) as db:
            # customer whose id is NOT numeric — no painel_id extractable
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("guest-abc", "Maria Sem ID", "5511666666666", "hybrid", now_iso, now_iso),
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("p-no-id", "guest-abc", 1, 3500, 55, "pending",
                 "renew-guest-abc-1m", now_iso),
            )
            await db.commit()

        with patch.object(whatsapp_client, "send_message", new=fake_wa_send):
            return await payments_mod._process_payment_confirmation(
                "renew-guest-abc-1m", paid=True, source="poller",
            )

    result = _run(go())
    assert result["status"] == "paid_no_painel_id"
    assert len(admin_msgs) == 1
    assert "renovar manualmente" in admin_msgs[0].lower()
    assert "Maria Sem ID" in admin_msgs[0]


def test_admin_alert_fires_when_painel_renewal_fails(tmp_path):
    """Renewal at painel.fun blew up → admin needs to know to renew manually."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from datetime import datetime, timezone
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_msgs = []

    async def fake_wa_send(phone, body, image_url=None, **kw):
        if phone == "5511777777777":
            admin_msgs.append(body)

    async def bad_renew(user_id, package_id):
        raise RuntimeError("painel.fun 500 boom")

    async def go():
        await database.init_db()
        await database.set_setting("admin_whatsapp", "5511777777777")
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("228116806", "Zé Cliente", "5511888888888", "p2p", now_iso, now_iso),
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("p-fail", "228116806", 1, 3500, 39, "pending",
                 "renew-228116806-1m", now_iso),
            )
            await db.commit()

        with patch.object(painel, "renew_user", new=bad_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa_send):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
            )

    result = _run(go())
    assert result["status"] == "renewal_failed"
    assert len(admin_msgs) == 1
    body = admin_msgs[0]
    assert "FALHOU" in body or "Falhou" in body or "falhou" in body.lower()
    assert "Zé Cliente" in body
    assert "painel.fun 500 boom" in body


def test_admin_alert_silent_when_setting_empty_on_renewal(tmp_path):
    """No admin_whatsapp configured → admin alerts must not raise or send."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from datetime import datetime, timezone
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    all_sends = []

    async def fake_wa_send(phone, body, image_url=None, **kw):
        all_sends.append((phone, body))

    async def fake_renew(user_id, package_id):
        return {"expires_at": "2027-01-01"}

    async def go():
        await database.init_db()
        # NOTE: no admin_whatsapp set
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("228116806", "Cliente X", "5511888888888", "iptv", now_iso, now_iso),
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("p-noadmin", "228116806", 1, 3500, 17, "pending",
                 "renew-228116806-1m", now_iso),
            )
            await db.commit()

        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa_send):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
            )

    result = _run(go())
    assert result["status"] == "renewed"
    # No admin message. Client might get one (if template enabled).
    admin_hits = [s for s in all_sends if s[0] == ""]  # no phone → nothing
    assert admin_hits == []
