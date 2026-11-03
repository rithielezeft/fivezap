"""Tests for the real InfinitePay Checkout webhook payload format.

Per official docs (infinitepay.io/checkout), the webhook body has NO `paid`
or `status` field. It arrives with `transaction_nsu`, `paid_amount`,
`invoice_slug`, `capture_method`, etc — and its mere delivery IS the
confirmation of a captured payment.

Also tests:
- Optional `?s=<secret>` origin check via `infinitepay_webhook_secret`.
- Backward-compatibility with legacy shapes (paid=True, status=paid, event=...).
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
    os.environ["SQLITE_PATH"] = str(tmp_path / "webhook.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    from services import infinitepay
    importlib.reload(infinitepay)
    return database


class _FakeRequest:
    def __init__(self, body: dict, query: dict = None, headers: dict = None):
        self._body = body
        self.query_params = query or {}
        self.headers = headers or {}

    async def json(self):
        return self._body


# ---------- Real InfinitePay payload ----------

def test_webhook_real_infinitepay_payload_marks_paid(tmp_path):
    """Real docs payload has NO `paid` field — must be treated as paid."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from datetime import datetime, timezone
    from routers import payments as payments_mod

    now_iso = datetime.now(timezone.utc).isoformat()
    calls = []

    async def fake_process(order_nsu, paid, source, raw):
        calls.append({"order_nsu": order_nsu, "paid": paid, "source": source})
        return {"ok": True, "status": "renewed", "payment_id": "x"}

    real_payload = {
        "invoice_slug": "abc123xyz",
        "amount": 3500,
        "paid_amount": 3535,
        "installments": 1,
        "capture_method": "credit_card",
        "transaction_nsu": "9f2a4b3c-uuid-transaction",
        "order_nsu": "renew-228116806-3m",
        "receipt_url": "https://checkout.infinitepay.io/receipt/abc123xyz",
        "items": [{"quantity": 1, "price": 3500, "description": "Renovação IPTV"}],
    }

    async def go():
        await database.init_db()
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest(real_payload))

    result = _run(go())
    assert result["status"] == "renewed"
    assert len(calls) == 1
    assert calls[0]["order_nsu"] == "renew-228116806-3m"
    assert calls[0]["paid"] is True   # <-- the key assertion
    assert calls[0]["source"] == "webhook"


def test_webhook_transaction_nsu_only_still_counts_as_paid(tmp_path):
    """Even when `paid_amount` is missing, presence of transaction_nsu +
    capture_method / invoice_slug is enough — InfinitePay only fires webhook
    after capture."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    calls = []

    async def fake_process(order_nsu, paid, source, raw):
        calls.append(paid)
        return {"ok": True, "status": "renewed", "payment_id": "x"}

    payload = {
        "order_nsu": "renew-777-1m",
        "transaction_nsu": "uuid",
        "capture_method": "pix",
        # No paid_amount, no paid, no status
    }

    async def go():
        await database.init_db()
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest(payload))

    _run(go())
    assert calls == [True]


def test_webhook_paid_amount_zero_is_not_paid(tmp_path):
    """paid_amount=0 with no other confirmation → NOT paid."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    calls = []

    async def fake_process(order_nsu, paid, source, raw):
        calls.append(paid)
        return {"ok": True, "status": "not_paid", "payment_id": "x"}

    payload = {
        "order_nsu": "renew-555-1m",
        "transaction_nsu": "uuid",
        "paid_amount": 0,
        # No capture_method, no invoice_slug — nothing indicates capture
    }

    async def go():
        await database.init_db()
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest(payload))

    _run(go())
    assert calls == [False]


# ---------- Legacy compatibility ----------

def test_webhook_legacy_paid_true_still_works(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    calls = []

    async def fake_process(order_nsu, paid, source, raw):
        calls.append(paid)
        return {"ok": True, "status": "renewed", "payment_id": "x"}

    async def go():
        await database.init_db()
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest({
                "order_nsu": "renew-100-1m", "paid": True,
            }))

    _run(go())
    assert calls == [True]


def test_webhook_legacy_status_paid_still_works(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    calls = []

    async def fake_process(order_nsu, paid, source, raw):
        calls.append(paid)
        return {"ok": True, "status": "renewed"}

    async def go():
        await database.init_db()
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest({
                "order_nsu": "renew-200-1m", "status": "paid",
            }))

    _run(go())
    assert calls == [True]


def test_webhook_missing_order_nsu_returns_error(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    async def go():
        await database.init_db()
        return await payments_mod.webhook(_FakeRequest({
            "transaction_nsu": "uuid", "paid_amount": 100,
        }))

    result = _run(go())
    assert result["ok"] is False
    assert result["error"] == "missing order_nsu"


# ---------- Secret origin check ----------

def test_webhook_rejects_when_secret_configured_but_missing_from_url(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    process_calls = []

    async def fake_process(*a, **kw):
        process_calls.append(1)
        return {"ok": True, "status": "renewed"}

    async def go():
        await database.init_db()
        await database.set_setting("infinitepay_webhook_secret", "s3cr3t")
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest(
                {"order_nsu": "x", "transaction_nsu": "u", "paid_amount": 100},
                query={},  # no ?s=
            ))

    result = _run(go())
    assert result == {"ok": False, "error": "bad_secret"}
    assert process_calls == []


def test_webhook_rejects_when_secret_mismatches(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    async def fake_process(*a, **kw):
        return {"ok": True, "status": "renewed"}

    async def go():
        await database.init_db()
        await database.set_setting("infinitepay_webhook_secret", "s3cr3t")
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest(
                {"order_nsu": "x", "transaction_nsu": "u", "paid_amount": 100},
                query={"s": "wrong"},
            ))

    assert _run(go()) == {"ok": False, "error": "bad_secret"}


def test_webhook_accepts_when_secret_matches(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    accepted = []

    async def fake_process(order_nsu, paid, source, raw):
        accepted.append(order_nsu)
        return {"ok": True, "status": "renewed", "payment_id": "x"}

    async def go():
        await database.init_db()
        await database.set_setting("infinitepay_webhook_secret", "s3cr3t")
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest(
                {"order_nsu": "renew-99-1m", "transaction_nsu": "u", "paid_amount": 100},
                query={"s": "s3cr3t"},
            ))

    result = _run(go())
    assert result["status"] == "renewed"
    assert accepted == ["renew-99-1m"]


def test_webhook_no_secret_configured_accepts_without_query(tmp_path):
    """Backward-compat: empty secret setting → skip origin check entirely."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    accepted = []

    async def fake_process(order_nsu, paid, source, raw):
        accepted.append(order_nsu)
        return {"ok": True, "status": "renewed"}

    async def go():
        await database.init_db()
        # secret empty by default
        with patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.webhook(_FakeRequest(
                {"order_nsu": "renew-77-1m", "transaction_nsu": "u", "paid_amount": 100},
            ))

    _run(go())
    assert accepted == ["renew-77-1m"]


# ---------- build_webhook_url helper ----------

def test_build_webhook_url_no_secret(tmp_path):
    database = _fresh_env(tmp_path)
    from services import infinitepay

    async def go():
        await database.init_db()
        return await infinitepay.build_webhook_url("https://whatsflow.example.com")

    assert _run(go()) == "https://whatsflow.example.com/api/payments/webhook"


def test_build_webhook_url_with_secret_urlencoded(tmp_path):
    database = _fresh_env(tmp_path)
    from services import infinitepay

    async def go():
        await database.init_db()
        await database.set_setting("infinitepay_webhook_secret", "hello world/=&")
        return await infinitepay.build_webhook_url("https://x.io")

    url = _run(go())
    assert url.startswith("https://x.io/api/payments/webhook?s=")
    # url-encoded special chars
    assert "hello%20world" in url
    assert "%2F" in url and "%3D" in url and "%26" in url


def test_build_webhook_url_empty_base_returns_none(tmp_path):
    database = _fresh_env(tmp_path)
    from services import infinitepay

    async def go():
        await database.init_db()
        return await infinitepay.build_webhook_url("")

    assert _run(go()) is None
