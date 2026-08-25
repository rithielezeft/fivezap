"""Tests for the phone-resolution + template fallback path in
_process_payment_confirmation.

Real-world scenario reported: payment confirmed, but the customer never
got the "renewal_success" template. Root causes we defend against here:

1. Customer's `whatsapp` was empty in SQLite (extract failed at auto-create)
   → we must fall back to Mongo and then to the painel.fun cache.
2. `renewal_success` notification template was disabled or missing
   → we must still send a minimal hardcoded confirmation.
3. Even in the worst case (no phone anywhere), the admin must be notified
   with a clear reason.
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
    os.environ["SQLITE_PATH"] = str(tmp_path / "notify_fallback.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    from services import notifier
    importlib.reload(notifier)
    return database


async def _seed(database, customer_row, payment_row):
    import aiosqlite
    await database.init_db()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO customers "
            "(id, name, whatsapp, system_type, painel_username, expires_at, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (customer_row["id"], customer_row["name"], customer_row["whatsapp"],
             customer_row["system_type"], customer_row.get("painel_username", ""),
             customer_row.get("expires_at", ""),
             customer_row["created_at"], customer_row["updated_at"]),
        )
        await db.execute(
            "INSERT OR REPLACE INTO payments "
            "(id, customer_id, plan_months, amount_cents, package_id, status, "
            " order_nsu, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (payment_row["id"], payment_row["customer_id"], payment_row["plan_months"],
             payment_row["amount_cents"], payment_row["package_id"],
             payment_row.get("status", "pending"),
             payment_row["order_nsu"], payment_row["created_at"]),
        )
        await db.commit()


# ---------- Fallback 1: phone missing locally → resolved from painel cache ----------

def test_phone_falls_back_to_painel_cache_and_notifies(tmp_path):
    """SQLite has no phone, Mongo has no phone, but painel cache has a WA number.
    → we must resolve it and deliver the renewal_success template."""
    database = _fresh_env(tmp_path)
    from datetime import datetime, timezone
    from routers import payments as payments_mod
    from routers import painel_users as painel_users_mod
    from services import painel, whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    all_sends = []

    async def fake_wa(phone, body, image_url=None, **kw):
        all_sends.append({"phone": phone, "body": body})

    async def fake_renew(user_id, package_id, **kwargs):
        return {"expires_at": "2027-05-01"}

    async def fake_read_cache():
        # painel cache has a user with whatsapp in the extractor-friendly `as_number`
        return ([{
            "id": "228116806",
            "username": "cliente_x",
            "full_name": "Cliente Sem Zap Local",
            "as_number": "5511987654321",
            "system": 1,
        }], {})

    async def go():
        await _seed(
            database,
            {
                "id": "228116806", "name": "Cliente Sem Zap Local",
                "whatsapp": "",  # <-- empty locally
                "system_type": "iptv",
                "painel_username": "cliente_x",
                "created_at": now_iso, "updated_at": now_iso,
            },
            {
                "id": "p-fb-1", "customer_id": "228116806", "plan_months": 1,
                "amount_cents": 3500, "package_id": 17,
                "order_nsu": "renew-228116806-1m", "created_at": now_iso,
            },
        )
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(painel_users_mod, "_read_cache", new=fake_read_cache), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
            )

    result = _run(go())
    assert result["status"] == "renewed"

    # The resolved phone MUST have been used to deliver the renewal_success template
    client_msgs = [s for s in all_sends if s["phone"] == "5511987654321"]
    assert len(client_msgs) >= 1
    assert "Pagamento confirmado" in client_msgs[0]["body"]

    # Local SQLite must now have the phone persisted (for next time)
    import aiosqlite
    async def check():
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT whatsapp FROM customers WHERE id = ?", ("228116806",))
            row = await cur.fetchone()
            return dict(row)
    persisted = _run(check())
    assert persisted["whatsapp"] == "5511987654321"


# ---------- Fallback 2: template disabled → hardcoded message still fires ----------

def test_hardcoded_fallback_when_template_disabled(tmp_path):
    """If `renewal_success` is disabled/missing, we must send a minimal
    hardcoded message so the client is not left in silence."""
    database = _fresh_env(tmp_path)
    from datetime import datetime, timezone
    import aiosqlite
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    sent = []

    async def fake_wa(phone, body, image_url=None, **kw):
        sent.append({"phone": phone, "body": body})

    async def fake_renew(user_id, package_id, **kwargs):
        return {"expires_at": "2027-06-15"}

    async def go():
        await _seed(
            database,
            {"id": "228888", "name": "Beltrano", "whatsapp": "5511900001111",
             "system_type": "hybrid", "created_at": now_iso, "updated_at": now_iso},
            {"id": "p-tmpl-off", "customer_id": "228888", "plan_months": 3,
             "amount_cents": 9000, "package_id": 43,
             "order_nsu": "renew-228888-3m", "created_at": now_iso},
        )
        # Explicitly disable the renewal_success template
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE notification_templates SET enabled = 0 WHERE event_key = 'renewal_success'"
            )
            await db.commit()

        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228888-3m", paid=True, source="webhook",
            )

    result = _run(go())
    assert result["status"] == "renewed"

    # Client received the hardcoded fallback (not the template)
    client_msgs = [s for s in sent if s["phone"] == "5511900001111"]
    assert len(client_msgs) == 1
    body = client_msgs[0]["body"]
    assert "Beltrano" in body
    assert "3 mês" in body
    assert "Pagamento confirmado" in body


# ---------- Admin alert reflects notification status ----------

def test_admin_alert_shows_notify_status_success(tmp_path):
    database = _fresh_env(tmp_path)
    from datetime import datetime, timezone
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_msgs = []

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511777777777":
            admin_msgs.append(body)

    async def fake_renew(user_id, package_id, **kwargs):
        return {"expires_at": "2027-06-15"}

    async def go():
        await _seed(
            database,
            {"id": "228700", "name": "OK Guy", "whatsapp": "5511900002222",
             "system_type": "iptv", "created_at": now_iso, "updated_at": now_iso},
            {"id": "p-ok-status", "customer_id": "228700", "plan_months": 1,
             "amount_cents": 3500, "package_id": 17,
             "order_nsu": "renew-228700-1m", "created_at": now_iso},
        )
        await database.set_setting("admin_whatsapp", "5511777777777")
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228700-1m", paid=True, source="webhook",
            )

    _run(go())
    assert len(admin_msgs) == 1
    assert "sim (template)" in admin_msgs[0]


def test_admin_alert_shows_notify_status_when_no_phone(tmp_path):
    """No phone anywhere → admin must be told the client wasn't notified,
    with a clear reason."""
    database = _fresh_env(tmp_path)
    from datetime import datetime, timezone
    from routers import payments as payments_mod
    from routers import painel_users as painel_users_mod
    from services import painel, whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_msgs = []

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511777777777":
            admin_msgs.append(body)

    async def fake_renew(user_id, package_id, **kwargs):
        return {"expires_at": "2027-06-15"}

    async def empty_cache():
        return ([], {})

    async def go():
        await _seed(
            database,
            {"id": "228999", "name": "No Phone Guy", "whatsapp": "",
             "system_type": "iptv", "created_at": now_iso, "updated_at": now_iso},
            {"id": "p-no-phone", "customer_id": "228999", "plan_months": 1,
             "amount_cents": 3500, "package_id": 17,
             "order_nsu": "renew-228999-1m", "created_at": now_iso},
        )
        await database.set_setting("admin_whatsapp", "5511777777777")
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(painel_users_mod, "_read_cache", new=empty_cache), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228999-1m", paid=True, source="webhook",
            )

    _run(go())
    assert len(admin_msgs) == 1
    assert "sem número no cadastro" in admin_msgs[0]


def test_admin_alert_shows_notify_status_when_template_disabled(tmp_path):
    """Template off → client got the hardcoded fallback → admin msg should
    say that clearly."""
    database = _fresh_env(tmp_path)
    from datetime import datetime, timezone
    import aiosqlite
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_msgs = []

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511777777777":
            admin_msgs.append(body)

    async def fake_renew(user_id, package_id, **kwargs):
        return {"expires_at": "2027-06-15"}

    async def go():
        await _seed(
            database,
            {"id": "228321", "name": "TplOff", "whatsapp": "5511900003333",
             "system_type": "iptv", "created_at": now_iso, "updated_at": now_iso},
            {"id": "p-tpl-off-admin", "customer_id": "228321", "plan_months": 1,
             "amount_cents": 3500, "package_id": 17,
             "order_nsu": "renew-228321-1m", "created_at": now_iso},
        )
        await database.set_setting("admin_whatsapp", "5511777777777")
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE notification_templates SET enabled = 0 WHERE event_key = 'renewal_success'"
            )
            await db.commit()

        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228321-1m", paid=True, source="webhook",
            )

    _run(go())
    assert len(admin_msgs) == 1
    assert "mensagem padrão" in admin_msgs[0]
    assert "template desabilitado" in admin_msgs[0]
