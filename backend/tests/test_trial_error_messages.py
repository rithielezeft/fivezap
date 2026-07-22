"""Bug fix: friendly error messages when trial creation fails.

Before, the client saw raw technical errors like:
    ❌ Não conseguimos criar seu teste agora.
    Motivo: Create trial failed: 400 — {"message":"O campo password format is invalid."}

After, the client sees a human message + is asked to retry the command;
technical details go to the admin via send_admin_alert.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "trial_err.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    _run(_db.init_db())
    return _db


async def _seed_template(system_type="iptv", trigger="!teste iptv"):
    import aiosqlite
    import database
    from models import new_id, now_iso
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT INTO command_templates (id, name, trigger_command, system_type, "
            "requires_mac, package_id, enabled, trigger_source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), "Teste IPTV", trigger, system_type, 0, 0, 1, "both",
             now_iso()),
        )
        await db.commit()


def _run_bot_with_painel_error(error_msg, tmp_path):
    """Simulate the bot receiving '!teste iptv' when painel raises `error_msg`."""
    _fresh_env(tmp_path)
    _run(_seed_template())

    from services import bot, whatsapp_client, painel
    # Clear the in-memory dedup so each test isn't suppressed by prior runs.
    bot._recent_messages.clear()

    sent_messages = []

    async def fake_send_message(phone, body, **kw):
        sent_messages.append({"phone": phone, "body": body})
        return True

    async def fake_create_trial(**kwargs):
        raise RuntimeError(error_msg)

    async def go():
        with patch.object(whatsapp_client, "send_message", new=fake_send_message), \
             patch.object(painel, "create_trial", new=fake_create_trial), \
             patch("services.notifier.send_admin_alert", new=AsyncMock(return_value=True)):
            await bot.process_incoming_message(
                phone="5511999998888",
                body="!teste iptv",
                from_me=False,
            )
        return sent_messages

    return _run(go())


def test_password_format_invalid_maps_to_friendly_retry_message(tmp_path):
    """The exact bug reported by the user."""
    err = 'Create trial failed: 400 — {"message":"O campo password format is invalid."}'
    msgs = _run_bot_with_painel_error(err, tmp_path)

    # Find the client-facing message (there should be at least one).
    client_msgs = [m for m in msgs if m["phone"] == "5511999998888"]
    assert client_msgs, f"Client got no message. All sends: {msgs}"

    body = client_msgs[-1]["body"]
    body_lower = body.lower()
    # Must NOT leak technical details
    assert "400" not in body, f"Message leaks status code: {body}"
    assert "password" not in body_lower, f"Message leaks 'password': {body}"
    assert "format is invalid" not in body_lower, f"Message leaks error: {body}"
    assert "json" not in body_lower and "{" not in body
    # Must include a retry hint referencing the command
    assert "!teste iptv" in body_lower or "envie o comando" in body_lower, (
        f"Message doesn't ask to retry: {body}"
    )
    # Must be friendly-toned (no "avisamos o suporte")
    assert "gentileza" in body_lower or "por gentileza" in body_lower


def test_username_taken_maps_to_friendly_message(tmp_path):
    err = 'Create trial failed: 409 — {"message":"username already taken"}'
    msgs = _run_bot_with_painel_error(err, tmp_path)
    body = [m for m in msgs if m["phone"] == "5511999998888"][-1]["body"].lower()
    assert "gerar outro" in body or "outro" in body
    assert "409" not in body
    assert "username" not in body  # not the raw word


def test_insufficient_credits_maps_to_specific_message(tmp_path):
    err = 'Create trial failed: 402 — {"message":"insufficient credits"}'
    msgs = _run_bot_with_painel_error(err, tmp_path)
    body = [m for m in msgs if m["phone"] == "5511999998888"][-1]["body"].lower()
    assert "cr\u00e9dito" in body or "sem cr\u00e9ditos" in body
    assert "equipe" in body or "avisada" in body


def test_timeout_maps_to_wait_message(tmp_path):
    err = "painel.fun request timed out after 30s"
    msgs = _run_bot_with_painel_error(err, tmp_path)
    body = [m for m in msgs if m["phone"] == "5511999998888"][-1]["body"].lower()
    assert "lento" in body or "aguarde" in body or "segundos" in body


def test_generic_error_still_asks_retry(tmp_path):
    """Unknown errors should still get a friendly retry message."""
    err = "some really weird internal error nobody expected"
    msgs = _run_bot_with_painel_error(err, tmp_path)
    body = [m for m in msgs if m["phone"] == "5511999998888"][-1]["body"].lower()
    assert "n\u00e3o consegui" in body or "n\u00e3o conseguimos" in body
    # Must NOT leak the raw error
    assert "weird internal" not in body
    # Must ask to retry
    assert "!teste iptv" in body or "envie o comando" in body


def test_admin_gets_technical_details(tmp_path):
    """Admin alert receives the FULL technical error for debugging."""
    _fresh_env(tmp_path)
    _run(_seed_template())

    from services import bot, whatsapp_client, painel
    bot._recent_messages.clear()

    admin_calls = []

    async def fake_send_admin_alert(msg):
        admin_calls.append(msg)
        return True

    async def fake_create_trial(**kwargs):
        raise RuntimeError('Create trial failed: 400 — {"message":"O campo password format is invalid."}')

    async def go():
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)), \
             patch.object(painel, "create_trial", new=fake_create_trial), \
             patch("services.notifier.send_admin_alert", new=fake_send_admin_alert):
            await bot.process_incoming_message(
                phone="5511999998888",
                body="!teste iptv",
                from_me=False,
            )
        return admin_calls

    calls = _run(go())
    assert calls, "Admin must be notified about trial failures"
    admin_msg = calls[0]
    # Admin msg keeps the technical details
    assert "password format is invalid" in admin_msg
    assert "5511999998888" in admin_msg
    assert "IPTV" in admin_msg.upper()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
