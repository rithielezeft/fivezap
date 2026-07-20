"""Tests: `new_expires_at` MUST be populated in the renewal confirmation
template — even when painel.fun's `renew_user` response doesn't include the
expiration date. We fall back to computing base_date + plan_months × 30d.

Also validates ISO date normalization to Brazilian dd/mm/aaaa.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "exp.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    from services import notifier
    importlib.reload(notifier)
    return database


async def _seed(database, expires_at="", plan_months=3):
    import aiosqlite
    now_iso_val = datetime.now(timezone.utc).isoformat()
    await database.init_db()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO customers "
            "(id, name, whatsapp, system_type, expires_at, created_at, updated_at) "
            "VALUES ('228116806', 'João Cliente', '5511900001111', 'iptv', ?, ?, ?)",
            (expires_at, now_iso_val, now_iso_val),
        )
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
            " package_id, status, order_nsu, created_at)"
            " VALUES ('p-exp', '228116806', ?, 9000, 43, 'pending',"
            " 'renew-228116806-3m', ?)",
            (plan_months, now_iso_val),
        )
        await db.commit()


# ---------- painel returns clean date ----------

def test_iso_date_normalized_to_br_format(tmp_path):
    """Painel returns '2027-05-15' → template must see '15/05/2027'."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    captured = {}

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511900001111":
            captured["body"] = body

    async def fake_renew(user_id, package_id):
        return {"expires_at": "2027-05-15"}

    async def go():
        await _seed(database)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-3m", paid=True, source="webhook",
            )

    result = _run(go())
    assert result["status"] == "renewed"
    assert "15/05/2027" in captured["body"]
    assert "2027-05-15" not in captured["body"]  # raw ISO must not leak


def test_full_iso_timestamp_normalized_to_br(tmp_path):
    """Painel returns '2027-05-15T23:59:59Z' → '15/05/2027'."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    captured = {}

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511900001111":
            captured["body"] = body

    async def fake_renew(user_id, package_id):
        return {"expires_at": "2027-05-15T23:59:59Z"}

    async def go():
        await _seed(database)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-3m", paid=True, source="webhook",
            )

    _run(go())
    assert "15/05/2027" in captured["body"]


def test_unix_timestamp_normalized_to_br(tmp_path):
    """Painel returns Unix ts → dd/mm/yyyy."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    captured = {}

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511900001111":
            captured["body"] = body

    async def fake_renew(user_id, package_id):
        # 2027-05-15 00:00 UTC
        return {"expires_at": 1810771200}

    async def go():
        await _seed(database)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-3m", paid=True, source="webhook",
            )

    _run(go())
    assert "20/05/2027" in captured["body"]


# ---------- painel returns nothing → project locally ----------

def test_missing_expiry_projected_from_current_customer_date(tmp_path):
    """Painel returns no expiry; customer has expires_at=2027-01-01 in DB.
    Expected: 2027-01-01 + 3 months × 30 days = 2027-04-01."""
    database = _fresh_env(tmp_path, )
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    captured = {}

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511900001111":
            captured["body"] = body

    async def fake_renew(user_id, package_id):
        return {}  # <-- painel returns nothing

    async def go():
        await _seed(database, expires_at="2027-01-01", plan_months=3)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-3m", paid=True, source="webhook",
            )

    _run(go())
    # 2027-01-01 + 90d = 2027-04-01
    assert "01/04/2027" in captured["body"], captured["body"]


def test_missing_expiry_and_expired_customer_projects_from_today(tmp_path):
    """Painel returns nothing AND customer already expired → count from today."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    captured = {}

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511900001111":
            captured["body"] = body

    async def fake_renew(user_id, package_id):
        return {}

    async def go():
        await _seed(database, expires_at="2020-01-01", plan_months=1)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-3m", paid=True, source="webhook",
            )

    _run(go())
    # Should be roughly today + 30 days — assert it's a valid dd/mm/yyyy string
    # in the future rather than empty.
    import re
    m = re.search(r"(\d{2}/\d{2}/\d{4})", captured["body"])
    assert m is not None, captured["body"]
    dt = datetime.strptime(m.group(1), "%d/%m/%Y")
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    assert 25 <= (dt - today).days <= 32, f"Projected date {dt} not around today+30d"


def test_template_body_has_name_months_and_expires(tmp_path):
    """Full end-to-end: template body must contain name, months, and expires."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    captured = {}

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511900001111":
            captured["body"] = body

    async def fake_renew(user_id, package_id):
        return {"expires_at": "2027-05-15"}

    async def go():
        await _seed(database, plan_months=3)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            return await payments_mod._process_payment_confirmation(
                "renew-228116806-3m", paid=True, source="webhook",
            )

    _run(go())
    body = captured["body"]
    assert "João Cliente" in body       # name
    assert "3 mês(es)" in body           # plan_months
    assert "15/05/2027" in body          # normalized expires
    assert "Pagamento confirmado" in body
