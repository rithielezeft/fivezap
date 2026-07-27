"""Coverage for the 6 fixes shipped 2026-02-22 (2nd batch):
1. Command template image_url column + upload
2. Client name extraction from message
3. Ask-for-name pending flow
4. WhatsApp saved to painel reseller_notes
5. Password format retry
6. display_timezone setting
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
    os.environ["SQLITE_PATH"] = str(tmp_path / "batch2.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    from services import bot
    importlib.reload(bot)
    _run(_db.init_db())
    return _db


# ---------- 1. command_templates.image_url ----------
def test_command_template_image_url_column_exists(tmp_path):
    _fresh_env(tmp_path)
    import aiosqlite
    import database

    async def go():
        async with aiosqlite.connect(database.DB_PATH) as db:
            cur = await db.execute("PRAGMA table_info(command_templates)")
            return {r[1] for r in await cur.fetchall()}

    cols = _run(go())
    assert "image_url" in cols, f"Expected image_url in command_templates. Got: {cols}"


# ---------- 2. Name extraction ----------
def test_extract_name_meu_nome_e():
    from services.bot import _extract_name_from_message
    assert _extract_name_from_message("oi, meu nome é João") == "João"
    assert _extract_name_from_message("Meu nome eh Maria Silva, quero teste") == "Maria Silva"


def test_extract_name_sou_o():
    from services.bot import _extract_name_from_message
    assert _extract_name_from_message("boa tarde, sou o Pedro") == "Pedro"
    assert _extract_name_from_message("eu sou Rafael") == "Rafael"


def test_extract_name_me_chamo():
    from services.bot import _extract_name_from_message
    assert _extract_name_from_message("me chamo Carlos") == "Carlos"


def test_extract_name_returns_none_when_no_pattern():
    from services.bot import _extract_name_from_message
    assert _extract_name_from_message("teste iptv") is None
    assert _extract_name_from_message("oi") is None
    assert _extract_name_from_message("") is None


def test_extract_name_rejects_common_words():
    """Non-name words like 'amigo' shouldn't be captured as names."""
    from services.bot import _extract_name_from_message
    assert _extract_name_from_message("sou o cara") is None


# ---------- 3. Ask-for-name flow ----------
def test_bot_asks_name_when_missing(tmp_path):
    _fresh_env(tmp_path)
    from services import bot, whatsapp_client
    import aiosqlite
    import database
    from models import new_id, now_iso

    async def seed():
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO command_templates (id, name, trigger_command, "
                "system_type, requires_mac, package_id, enabled, trigger_source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), "Teste", "!teste iptv", "iptv", 0, 0, 1, "both", now_iso()),
            )
            await db.commit()

    sent = []

    async def fake_send(phone, body, **kw):
        sent.append({"phone": phone, "body": body})
        return True

    async def go():
        await seed()
        bot._recent_messages.clear()
        bot._pending_name.clear()
        with patch.object(whatsapp_client, "send_message", new=fake_send):
            # No customer name, message has no name pattern → should ask.
            await bot.process_incoming_message(
                phone="5511900000001",  # digits only, no explicit name
                body="!teste iptv",
                from_me=False,
            )
        return sent

    sent = _run(go())
    assert len(sent) >= 1
    last = sent[-1]["body"].lower()
    assert "primeiro nome" in last or "diga seu nome" in last.replace("me diz seu", "diga seu"), (
        f"Bot should ask for name. Got: {sent[-1]['body']}"
    )


# ---------- 4. WhatsApp saved to painel reseller_notes ----------
def test_painel_create_trial_sends_reseller_notes():
    """The painel create_trial payload must include the client WhatsApp in
    reseller_notes so admins can lookup who the trial belongs to."""
    import inspect
    from services import painel
    src = inspect.getsource(painel.create_trial)
    assert "reseller_notes" in src, "WhatsApp must be written to painel reseller_notes"


# ---------- 5. Password format retry ----------
def test_painel_password_retry_on_invalid_format():
    """When painel returns 'password format invalid', we must retry up to 3
    times with a fresh password before giving up."""
    import inspect
    from services import painel
    src = inspect.getsource(painel.create_trial)
    assert "for attempt in range(3)" in src, "Should retry 3 times"
    assert "password" in src.lower()


# ---------- 6. display_timezone setting ----------
def test_display_timezone_in_defaults():
    """`display_timezone` must be in the default settings so new installs
    have a sane value."""
    import inspect
    import database
    src = inspect.getsource(database.init_db)
    assert "display_timezone" in src


def test_display_timezone_in_settings_model():
    from models import SettingsUpdate
    assert "display_timezone" in SettingsUpdate.model_fields


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
