"""Test that POST /api/payments passes customer name+phone to InfinitePay
so the checkout form is pre-filled — improves conversion and lets InfinitePay
tie the payment back to the exact customer being renewed.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def test_create_payment_passes_customer_name_and_phone_to_infinitepay(monkeypatch, tmp_path):
    """The checkout link created by /api/payments must be pre-filled with the
    customer's name and phone (from Mongo/local). This is required for the
    InfinitePay webhook to correlate the payment with the right user_id and
    for the customer to skip the contact form on checkout."""
    from routers import payments as payments_mod
    from services import infinitepay, mongo_store
    import database
    import os
    import importlib
    import aiosqlite

    # Isolated SQLite
    os.environ["SQLITE_PATH"] = str(tmp_path / "test.db")
    importlib.reload(database)
    from routers import painel_users
    importlib.reload(painel_users)
    importlib.reload(payments_mod)

    captured = {}

    async def fake_create_link(**kwargs):
        captured.update(kwargs)
        return {"url": "https://checkout.infinitepay.io/x/abc",
                "raw": {}, "handle": "x", "http_status": 200}

    async def fake_mongo_lookup(painel_id):
        return {
            "_id": "228116806",
            "full_name": "Oscar da Silva",
            "whatsapp": "5511987654321",
            "system_type": "iptv",
            "exp_date_iso": "2026-08-15T16:20:52+00:00",
            "painel_username": "oscarnew",
        }

    async def fake_get_setting(key, default=None):
        return {
            "plan_price_3m": "99,50",
            "public_base_url": "https://whatsflow.example.com",
            "infinitepay_handle": "zeferius",
        }.get(key, default if default is not None else "")

    async def go():
        await database.init_db()
        for m, v in [(1, "35,00"), (3, "99,50"), (6, "160,00"), (12, "280,00")]:
            await database.set_setting(f"plan_price_{m}m", v)

        with patch.object(mongo_store, "find_customer_by_painel_id", new=fake_mongo_lookup), \
             patch.object(infinitepay, "create_payment_link", new=fake_create_link), \
             patch.object(mongo_store, "upsert_payment", new=AsyncMock(return_value="pid")), \
             patch.object(payments_mod, "get_setting", new=fake_get_setting):
            from routers.payments import PaymentCreate
            return await payments_mod.create_payment(
                PaymentCreate(customer_id="228116806", plan_months=3)
            )

    result = _run(go())
    assert result["amount_cents"] == 9950
    assert result["order_nsu"] == "renew-228116806-3m"
    # THE key assertions: InfinitePay got name + phone pre-filled
    assert captured.get("customer_name") == "Oscar da Silva", \
        f"customer_name missing in InfinitePay payload: {captured}"
    assert captured.get("customer_phone") == "5511987654321", \
        f"customer_phone missing (or not sanitized) in InfinitePay payload: {captured}"
    # And still has webhook_url + redirect_url set
    assert captured.get("webhook_url") == "https://whatsflow.example.com/api/payments/webhook"
    assert captured.get("redirect_url") == "https://whatsflow.example.com/pay/228116806?ok=1"


def test_create_payment_strips_whatsapp_suffixes(monkeypatch, tmp_path):
    """WhatsApp numbers stored as '5511987654321@c.us' or '@lid' must be
    stripped to digits-only before going to InfinitePay."""
    from routers import payments as payments_mod
    from services import infinitepay, mongo_store
    import database, os, importlib

    os.environ["SQLITE_PATH"] = str(tmp_path / "t2.db")
    importlib.reload(database)
    from routers import painel_users
    importlib.reload(painel_users)
    importlib.reload(payments_mod)

    captured = {}

    async def fake_create_link(**kwargs):
        captured.update(kwargs)
        return {"url": "x", "raw": {}, "handle": "y", "http_status": 200}

    async def fake_mongo_lookup(pid):
        return {
            "_id": pid,
            "full_name": "Ana Lu",
            "whatsapp": "5511987654321@c.us",
            "system_type": "p2p",
            "painel_username": "analu",
        }

    async def fake_get_setting(key, default=None):
        return {
            "plan_price_1m": "35,00",
            "public_base_url": "https://x.test",
            "infinitepay_handle": "z",
        }.get(key, default if default is not None else "")

    async def go():
        await database.init_db()
        with patch.object(mongo_store, "find_customer_by_painel_id", new=fake_mongo_lookup), \
             patch.object(infinitepay, "create_payment_link", new=fake_create_link), \
             patch.object(mongo_store, "upsert_payment", new=AsyncMock(return_value="pid")), \
             patch.object(payments_mod, "get_setting", new=fake_get_setting):
            from routers.payments import PaymentCreate
            await payments_mod.create_payment(PaymentCreate(customer_id="123", plan_months=1))

    _run(go())
    assert captured.get("customer_phone") == "5511987654321"
    assert "@" not in (captured.get("customer_phone") or "")
