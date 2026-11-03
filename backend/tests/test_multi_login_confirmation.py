"""Paying 2+ logins in one checkout → ONE confirmation listing every login,
password and new expiration; cache updated so /pay shows the new dates."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BODY = ("✅ Pagamento confirmado! Obrigado, {name} 🎉\nSeus dados de acesso:\n👤 Usuário: {user}\n"
        "🔑 senha: {password}\n📅 Vence em: {new_expires_at}\n🍀 Trevo: {clover_coupons}\n"
        "Seu acesso já está renovado. Bom proveito! 😃")


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "multi.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    from services import notifier
    importlib.reload(notifier)
    return database


async def _seed(database):
    import aiosqlite
    now = datetime.now(timezone.utc).isoformat()
    await database.init_db()
    users = [
        {"id": 111, "username": "joaonw", "password": "2a1yk4c7", "exp_date": 1700000000},
        {"id": 222, "username": "paulov4", "password": "jsjsh21", "exp_date": 1700000000},
    ]
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO customers (id, name, whatsapp, system_type, painel_username, created_at, updated_at) "
            "VALUES ('111', 'Udnan', '5511900001111', 'iptv', 'joaonw', ?, ?)", (now, now))
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, order_nsu, created_at, extra_customer_ids)"
            " VALUES ('p-multi', '111', 1, 7000, 17, 'pending', 'renew-111-1m', ?, ?)", (now, json.dumps(["222"])))
        await db.execute("INSERT OR REPLACE INTO painel_users_cache (id, data, updated_at) VALUES ('all', ?, ?)",
                         (json.dumps(users), now))
        await db.execute("UPDATE notification_templates SET body = ?, enabled = 1 WHERE event_key = 'renewal_success'", (BODY,))
        await db.commit()


def test_two_logins_single_combined_message(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from routers.painel_users import _read_cache
    from services import painel, whatsapp_client

    sent = []

    async def fake_wa(phone, body, image_url=None, **kw):
        if phone == "5511900001111":
            sent.append(body)

    async def fake_renew(user_id, package_id, **kwargs):
        return {"exp_date": 1796700000 if str(user_id) == "111" else 1796786400}

    async def go():
        await _seed(database)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            res = await payments_mod._process_payment_confirmation("renew-111-1m", paid=True, source="webhook")
        cache, _ = await _read_cache()
        return res, cache

    res, cache = asyncio.run(go())
    assert res["status"] == "renewed"
    assert len(sent) == 1, sent
    body = sent[0]
    assert "👤 Usuário: joaonw , paulov4" in body
    assert "2a1yk4c7 ( joaonw ) , jsjsh21 ( paulov4 )" in body
    d1 = datetime.fromtimestamp(1796700000, tz=timezone.utc).astimezone().strftime("%d/%m/%Y")
    assert "( joaonw ) e " in body and "( paulov4 )" in body
    by_id = {str(u["id"]): u for u in cache}
    assert by_id["111"]["exp_date"] == 1796700000
    assert by_id["222"]["exp_date"] == 1796786400
    assert d1[:2].isdigit()
