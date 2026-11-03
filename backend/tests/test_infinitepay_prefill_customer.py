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
    """The checkout link created by /api/payments must pre-fill the
    customer's PAINEL USERNAME as customer_name (so it binds the payment to
    that specific user_id in InfinitePay). Phone must be OMITTED (None) so
    the customer fills it themselves at checkout (opcional)."""
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
    # THE key assertions:
    # (a) customer_name = painel_username (not full_name) — binds the InfinitePay
    #     receipt to the specific user_id being renewed
    assert captured.get("customer_name") == "oscarnew", \
        f"Expected painel_username 'oscarnew' as customer_name, got: {captured.get('customer_name')!r}"
    # (b) customer_phone is None/absent — customer fills it themselves
    assert captured.get("customer_phone") in (None, ""), \
        f"customer_phone should NOT be pre-filled (optional), got: {captured.get('customer_phone')!r}"
    # And still has webhook_url + redirect_url set (redirect includes signed token)
    assert captured.get("webhook_url") == "https://whatsflow.example.com/api/payments/webhook"
    assert captured.get("redirect_url", "").startswith(
        "https://whatsflow.example.com/pay/228116806?ok=1&t="
    ), f"Expected signed redirect URL, got: {captured.get('redirect_url')}"


def test_create_payment_falls_back_to_name_when_no_username(monkeypatch, tmp_path):
    """If the customer somehow doesn't have painel_username, fall back to
    full_name to keep the checkout identifiable."""
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
            "painel_username": "",  # missing!
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
    # Fall back to full_name when username missing
    assert captured.get("customer_name") == "Ana Lu"
    # Phone still not pre-filled
    assert captured.get("customer_phone") in (None, "")
