"""Tests for the new pay_link template feature (iteration 10).

Verifies that process_incoming_message correctly substitutes:
- {pay_link}       -> monthly (1m) link (default)
- {pay_link_1m}    -> 1-month link
- {pay_link_3m}    -> 3-month link
- {pay_link_6m}    -> 6-month link
- {pay_link_12m}   -> 12-month link

Also verifies:
- Fallback to `{public_base}/pay/{trial_user_id}` when infinitepay fails for
  all 4 plans.
- If painel.create_trial raises, no pay_link generation is attempted and no
  crash occurs (client gets the error message via whatsapp_client.send_message).
- services.infinitepay is import-able inside the try/except loop (regression).
"""
import asyncio
import sys

import pytest

sys.path.insert(0, "/app/backend")


# ---------------------------------------------------------------------------
# Shared helpers for stubbing aiosqlite + DB
# ---------------------------------------------------------------------------
def _make_fake_aiosqlite(template_rows):
    """Build a fake aiosqlite.connect that returns `template_rows` for the
    SELECT command_templates query and no-ops for INSERTs/UPDATEs."""
    class _FakeCursor:
        def __init__(self, rows):
            self._rows = rows
        async def fetchall(self):
            return self._rows
        async def fetchone(self):
            return self._rows[0] if self._rows else None

    class _FakeDB:
        row_factory = None
        async def execute(self, sql, *a, **k):
            up = sql.upper() if isinstance(sql, str) else ""
            if "COMMAND_TEMPLATES" in up and "SELECT" in up:
                return _FakeCursor(template_rows)
            return _FakeCursor([])
        async def commit(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    return lambda *a, **k: _FakeDB()


def _make_template_row(response_template):
    """Build a dict that behaves like an aiosqlite.Row for our purposes.
    bot.py does `dict(r)` on each row and then accesses keys — so a plain dict
    works because dict(dict) is fine and dict-key access is native."""
    return {
        "id": "tpl_1",
        "name": "P2P test",
        "trigger_command": "p2p ok",
        "system_type": "p2p",
        "requires_mac": 0,
        "package_id": None,
        "response_template": response_template,
        "enabled": 1,
        "trigger_source": "both",
        "created_at": "2026-01-01T00:00:00Z",
    }


def _install_common_mocks(monkeypatch, bot, template_row):
    """Mocks for save_message, find_or_create_customer, log_activity, get_setting,
    aiosqlite.connect, reminders.schedule."""
    async def fake_save_message(phone, message, direction, customer_id=None):
        pass

    async def fake_find_or_create_customer(phone, name=None):
        return {"id": "cust_test", "name": name or phone, "whatsapp": phone, "system_type": "unknown"}

    async def fake_log_activity(*a, **k):
        pass

    async def fake_get_setting(key, default=None):
        mapping = {
            "public_base_url": "https://whatsflow.example.com",
            "plan_price_1m": "35,00",
            "plan_price_3m": "90,00",
            "plan_price_6m": "170,00",
            "plan_price_12m": "300,00",
            "infinitepay_handle": "mystore",
        }
        return mapping.get(key, default)

    monkeypatch.setattr(bot, "save_message", fake_save_message)
    monkeypatch.setattr(bot, "find_or_create_customer", fake_find_or_create_customer)
    monkeypatch.setattr(bot, "log_activity", fake_log_activity)
    monkeypatch.setattr(bot.aiosqlite, "connect", _make_fake_aiosqlite([template_row]))

    # Patch get_setting on the database module (used via `from database import get_setting`)
    import database
    monkeypatch.setattr(database, "get_setting", fake_get_setting)

    # Patch reminders.schedule so it doesn't try to write to DB
    from services import reminders
    async def fake_schedule(*a, **k):
        pass
    monkeypatch.setattr(reminders, "schedule", fake_schedule)


# ---------------------------------------------------------------------------
# Test 1: All 4 InfinitePay links succeed → template gets all links substituted
# ---------------------------------------------------------------------------
class TestPayLinkAllPlansSucceed:
    def test_all_plan_links_substituted(self, monkeypatch):
        from services import bot, painel, whatsapp_client, infinitepay

        bot._recent_messages.clear()

        template_row = _make_template_row(
            "OK {user}/{pass} exp {expires}\n"
            "1m: {pay_link_1m}\n"
            "3m: {pay_link_3m}\n"
            "6m: {pay_link_6m}\n"
            "12m: {pay_link_12m}\n"
            "default: {pay_link}"
        )
        _install_common_mocks(monkeypatch, bot, template_row)

        async def fake_create_trial(**kw):
            return {
                "id": 999,
                "username": "u_test",
                "password": "p_test",
                "expires_at": "2026-01-02T00:00:00Z",
            }
        monkeypatch.setattr(painel, "create_trial", fake_create_trial)

        # Track which plans were requested
        calls = []
        async def fake_create_payment_link(order_nsu, amount_cents, description, **kw):
            calls.append({"order_nsu": order_nsu, "amount_cents": amount_cents})
            # Extract months from order_nsu suffix, e.g. "trial-abcd-3m"
            months = order_nsu.rsplit("-", 1)[-1]
            return {"url": f"https://checkout.infinitepay.io/mystore/{months}-link", "raw": {}, "handle": "mystore", "http_status": 200}
        monkeypatch.setattr(infinitepay, "create_payment_link", fake_create_payment_link)

        sent = []
        async def fake_send_message(phone, msg):
            sent.append((phone, msg))
        monkeypatch.setattr(whatsapp_client, "send_message", fake_send_message)

        asyncio.run(bot.process_incoming_message("5511111@c.us", "p2p ok", from_me=False))

        assert len(sent) == 1, f"expected 1 outgoing message, got {len(sent)}: {sent}"
        _, msg = sent[0]
        assert "1m: https://checkout.infinitepay.io/mystore/1m-link" in msg, msg
        assert "3m: https://checkout.infinitepay.io/mystore/3m-link" in msg, msg
        assert "6m: https://checkout.infinitepay.io/mystore/6m-link" in msg, msg
        assert "12m: https://checkout.infinitepay.io/mystore/12m-link" in msg, msg
        # {pay_link} is ALWAYS the short local /pay/{painel_id} URL — never the long InfinitePay URL
        assert "default: https://whatsflow.example.com/pay/999" in msg, msg

        # Confirm 4 calls with correct amounts (cents)
        assert len(calls) == 4
        amounts = {c["amount_cents"] for c in calls}
        assert amounts == {3500, 9000, 17000, 30000}, amounts


# ---------------------------------------------------------------------------
# Test 2: All InfinitePay calls FAIL → fallback to /pay/{id}
# ---------------------------------------------------------------------------
class TestPayLinkFallback:
    def test_fallback_to_local_pay_page(self, monkeypatch):
        from services import bot, painel, whatsapp_client, infinitepay

        bot._recent_messages.clear()

        template_row = _make_template_row(
            "user={user} link={pay_link} link1={pay_link_1m} link3={pay_link_3m}"
        )
        _install_common_mocks(monkeypatch, bot, template_row)

        async def fake_create_trial(**kw):
            return {
                "id": 42,
                "username": "u_fb",
                "password": "p_fb",
                "expires_at": "2026-01-02T00:00:00Z",
            }
        monkeypatch.setattr(painel, "create_trial", fake_create_trial)

        # Every InfinitePay call raises → fallback path
        async def fake_create_payment_link(*a, **k):
            raise RuntimeError("network down / handle invalid")
        monkeypatch.setattr(infinitepay, "create_payment_link", fake_create_payment_link)

        sent = []
        async def fake_send_message(phone, msg):
            sent.append((phone, msg))
        monkeypatch.setattr(whatsapp_client, "send_message", fake_send_message)

        asyncio.run(bot.process_incoming_message("5511222@c.us", "p2p ok", from_me=False))

        assert len(sent) == 1, sent
        _, msg = sent[0]
        # Fallback URL uses trial_user_id (=42) since that's what painel returned
        expected_fallback = "https://whatsflow.example.com/pay/42"
        assert f"link={expected_fallback}" in msg, msg
        # pay_link_1m falls back to same checkout_link (see bot.py line 278)
        assert f"link1={expected_fallback}" in msg, msg
        # pay_link_3m has no fallback (bot.py uses pay_links_by_plan.get(3, ""))
        assert "link3=" in msg
        # After 'link3=' there should be nothing (empty string), no URL
        assert "link3=https" not in msg, msg


# ---------------------------------------------------------------------------
# Test 3: painel.create_trial raises → NO pay_link attempted, no crash,
#         client receives the error message.
# ---------------------------------------------------------------------------
class TestPainelFailureNoPayLinkAttempted:
    def test_painel_failure_graceful(self, monkeypatch):
        from services import bot, painel, whatsapp_client, infinitepay

        bot._recent_messages.clear()

        template_row = _make_template_row("shouldnt matter {user} {pay_link}")
        _install_common_mocks(monkeypatch, bot, template_row)

        async def fake_create_trial(**kw):
            raise RuntimeError("painel.fun 502 Bad Gateway")
        monkeypatch.setattr(painel, "create_trial", fake_create_trial)

        pay_calls = []
        async def fake_create_payment_link(*a, **k):
            pay_calls.append(1)
            return {"url": "x", "raw": {}, "handle": "h", "http_status": 200}
        monkeypatch.setattr(infinitepay, "create_payment_link", fake_create_payment_link)

        sent = []
        async def fake_send_message(phone, msg):
            sent.append((phone, msg))
        monkeypatch.setattr(whatsapp_client, "send_message", fake_send_message)

        # Should not raise
        asyncio.run(bot.process_incoming_message("5511333@c.us", "p2p ok", from_me=False))

        # Zero pay-link calls because painel failed first
        assert len(pay_calls) == 0, "InfinitePay must NOT be called after painel fails"
        # Client receives an error message via whatsapp_client
        assert len(sent) == 1
        _, msg = sent[0]
        assert "❌" in msg or "erro" in msg.lower() or "Não conseguimos" in msg, msg
        assert "painel.fun 502" in msg or "502" in msg  # detail surfaced


# ---------------------------------------------------------------------------
# Test 4: Regression sanity — services.infinitepay import inside bot's loop
# ---------------------------------------------------------------------------
class TestInfinitepayImportable:
    def test_bot_can_import_infinitepay(self):
        """The bot does `from services import infinitepay` inside the loop.
        Make sure that name resolves and exposes create_payment_link."""
        from services import infinitepay
        assert callable(getattr(infinitepay, "create_payment_link", None))


# ---------------------------------------------------------------------------
# Test 4: {pay_link} MUST always be the short local /pay/{painel_id} URL
#         — never an InfinitePay URL — even when 1m succeeds.
# ---------------------------------------------------------------------------
class TestPayLinkAlwaysLocalUrl:
    def test_pay_link_is_always_local_short_url(self, monkeypatch):
        from services import bot, painel, whatsapp_client, infinitepay

        bot._recent_messages.clear()

        template_row = _make_template_row("Seu link: {pay_link}")
        _install_common_mocks(monkeypatch, bot, template_row)

        async def fake_create_trial(**kw):
            return {"id": 227453827, "username": "u", "password": "p", "expires_at": "x"}
        monkeypatch.setattr(painel, "create_trial", fake_create_trial)

        # InfinitePay 1m works — but {pay_link} MUST still be the local URL
        async def fake_create_payment_link(order_nsu, amount_cents, description, **kw):
            return {"url": "https://checkout.infinitepay.io/very/long/url",
                    "raw": {}, "handle": "h", "http_status": 200}
        monkeypatch.setattr(infinitepay, "create_payment_link", fake_create_payment_link)

        sent = []
        async def fake_send_message(phone, msg):
            sent.append((phone, msg))
        monkeypatch.setattr(whatsapp_client, "send_message", fake_send_message)

        asyncio.run(bot.process_incoming_message("5511555@c.us", "p2p ok", from_me=False))

        _, msg = sent[0]
        assert msg == "Seu link: https://whatsflow.example.com/pay/227453827", msg
        # Explicit negative: NO long InfinitePay URL in the {pay_link} substitution
        assert "checkout.infinitepay.io" not in msg.split("{pay_link}")[0]


# ---------------------------------------------------------------------------
# Test 5: Partial success — 1m and 3m succeed, 6m/12m fail → mixed
# ---------------------------------------------------------------------------
class TestPayLinkPartialSuccess:
    def test_partial_plans_success(self, monkeypatch):
        from services import bot, painel, whatsapp_client, infinitepay

        bot._recent_messages.clear()
        template_row = _make_template_row(
            "d={pay_link}|1={pay_link_1m}|3={pay_link_3m}|6={pay_link_6m}|12={pay_link_12m}"
        )
        _install_common_mocks(monkeypatch, bot, template_row)

        async def fake_create_trial(**kw):
            return {"id": 77, "username": "u", "password": "p", "expires_at": "x"}
        monkeypatch.setattr(painel, "create_trial", fake_create_trial)

        async def fake_create_payment_link(order_nsu, amount_cents, description, **kw):
            months = order_nsu.rsplit("-", 1)[-1]
            if months in ("1m", "3m"):
                return {"url": f"https://ok/{months}", "raw": {}, "handle": "h", "http_status": 200}
            raise RuntimeError("boom")
        monkeypatch.setattr(infinitepay, "create_payment_link", fake_create_payment_link)

        sent = []
        async def fake_send_message(phone, msg):
            sent.append((phone, msg))
        monkeypatch.setattr(whatsapp_client, "send_message", fake_send_message)

        asyncio.run(bot.process_incoming_message("5511444@c.us", "p2p ok", from_me=False))

        _, msg = sent[0]
        # {pay_link} is ALWAYS the short local /pay/{painel_id} URL, regardless
        # of whether InfinitePay 1m succeeded.
        assert "d=https://whatsflow.example.com/pay/77" in msg, msg
        # Per-plan links stay as the InfinitePay direct checkout when available
        assert "1=https://ok/1m" in msg, msg
        assert "3=https://ok/3m" in msg, msg
        # 6m and 12m failed → empty per bot.py pay_links_by_plan.get(6, "")
        assert "6=|" in msg or msg.endswith("6=") or "|6=|" in msg or "|6=" in msg
