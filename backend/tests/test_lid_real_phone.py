"""Regression tests for LID (WhatsApp privacy protocol) phone extraction.

Bug reported by user (2026-02-27): "colega enviou o comando e o número dele
NÃO foi registrado automaticamente" — for LID users, phone_clean was
"12345@lid" and the bot sent whatsapp="" to painel.fun, so reseller_notes
was never populated.

Fix: Node service now extracts msg.getContact().number and forwards it as
`real_phone`. Backend backfills onto customers.whatsapp, and
_run_trial_creation reads it and passes to painel.create_trial as the
whatsapp arg — so reseller_notes gets set correctly for LID users too.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "lid.db")
    import importlib
    import database
    importlib.reload(database)
    from services import bot
    importlib.reload(bot)
    return database, bot


def _run(coro):
    return asyncio.run(coro)


def test_incoming_lid_backfills_real_phone_on_customer(tmp_path, monkeypatch):
    """When Node forwards `real_phone` for a @lid chat, the customer row
    must have `whatsapp` set to the real digits."""
    database, bot = _fresh_env(tmp_path)

    # Stub anything that would try to hit external services
    from services import whatsapp_client
    async def _noop_send(*a, **k): return {"ok": True}
    monkeypatch.setattr(whatsapp_client, "send_message", _noop_send)

    async def go():
        await database.init_db()
        # Send an incoming message that DOESN'T match any template (no templates
        # seeded), so we exercise only the identity+backfill path.
        await bot.process_incoming_message(
            phone="789456123@lid",
            body="ola",
            from_me=False,
            name="Colega Teste",
            real_phone="+55 11 94774-8236",
        )
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT id, name, whatsapp FROM customers")
            rows = [dict(r) for r in await cur.fetchall()]
        return rows

    rows = _run(go())
    assert len(rows) == 1, rows
    # whatsapp must be the digits-only version of the real_phone we sent
    assert rows[0]["whatsapp"] == "5511947748236", rows[0]
    assert rows[0]["name"] == "Colega Teste"


def test_incoming_lid_rejects_lid_shaped_real_phone(tmp_path, monkeypatch):
    """Regression for the +191134936608840 bug: if Node accidentally
    forwards the LID digits themselves as `real_phone` (15-18 digits), the
    backend MUST reject it and NOT store as customer.whatsapp — otherwise
    the painel would end up with a fake number in reseller_notes."""
    database, bot = _fresh_env(tmp_path)

    from services import whatsapp_client
    async def _noop_send(*a, **k): return {"ok": True}
    monkeypatch.setattr(whatsapp_client, "send_message", _noop_send)

    async def go():
        await database.init_db()
        # Simulate Node leaking the LID as real_phone (the exact bug user hit)
        await bot.process_incoming_message(
            phone="191134936608840@lid",
            body="ola",
            from_me=False,
            name="Cliente LID Suspeito",
            real_phone="191134936608840",  # 15-digit LID, NOT a phone
        )
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT whatsapp FROM customers")
            row = dict(await cur.fetchone())
        return row

    row = _run(go())
    # whatsapp must NOT be the LID digits — should stay as the original LID JID
    # (which find_or_create_customer stored on first insert)
    assert row["whatsapp"] != "191134936608840", (
        f"LID digits leaked into customers.whatsapp: {row}"
    )


def test_incoming_non_lid_does_not_overwrite_whatsapp(tmp_path, monkeypatch):
    """For non-LID chats we already had the real phone — don't clobber it
    with any `real_phone` field."""
    database, bot = _fresh_env(tmp_path)

    from services import whatsapp_client
    async def _noop_send(*a, **k): return {"ok": True}
    monkeypatch.setattr(whatsapp_client, "send_message", _noop_send)

    async def go():
        await database.init_db()
        await bot.process_incoming_message(
            phone="5511987654321@c.us",
            body="ola",
            from_me=False,
            name="Cliente Normal",
            real_phone=None,
        )
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT whatsapp FROM customers")
            row = dict(await cur.fetchone())
        return row

    row = _run(go())
    # phone_clean is 5511987654321 (dropped @c.us) — should be stored as-is
    assert row["whatsapp"] == "5511987654321", row


def test_run_trial_creation_sends_real_phone_to_painel_for_lid(tmp_path, monkeypatch):
    """The critical end-to-end assertion:

    LID chat → real_phone backfilled → _run_trial_creation passes it
    to painel.create_trial as `whatsapp=`, which becomes reseller_notes.
    """
    database, bot = _fresh_env(tmp_path)
    from services import whatsapp_client, painel

    async def _noop_send(*a, **k): return {"ok": True}
    monkeypatch.setattr(whatsapp_client, "send_message", _noop_send)

    # Capture what bot sends to painel.create_trial
    calls = []
    async def fake_create_trial(**kwargs):
        calls.append(kwargs)
        return {"id": 42, "username": "test01new", "password": "abc",
                "expires_at": "2026-03-01"}
    monkeypatch.setattr(painel, "create_trial", fake_create_trial)

    async def go():
        await database.init_db()
        # Seed a template that matches "teste"
        import aiosqlite
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO command_templates (id, name, trigger_command, "
                " requires_mac, system_type, response_template, enabled, "
                " created_at) "
                "VALUES ('t1', 'IPTV Teste', 'teste', 0, 'iptv', "
                "'✅ Ok {user}/{pass} {pay_link}', 1, ?)",
                (now,),
            )
            await db.commit()

        # LID customer sends trigger — Node forwarded real_phone
        await bot.process_incoming_message(
            phone="777888999@lid",
            body="teste",
            from_me=False,
            name="Colega LID",
            real_phone="5511911223344",
        )
    _run(go())

    assert len(calls) == 1, f"painel.create_trial not called: {calls}"
    # THE ASSERTION THAT LOCKS THIS BUG: whatsapp must be the real phone,
    # not "" (which would leave reseller_notes empty on painel).
    assert calls[0]["whatsapp"] == "5511911223344", (
        f"Expected whatsapp=5511911223344 (real phone), got {calls[0]!r}"
    )
    assert calls[0]["system_type"] == "iptv"
    assert calls[0]["name"] == "Colega LID"


def test_run_trial_creation_lid_without_real_phone_sends_empty(tmp_path, monkeypatch):
    """If Node couldn't resolve a real phone (contact.number = null for
    strict LID users), we still create the trial — just without whatsapp.
    This is a degradation, not a crash. reseller_notes stays empty."""
    database, bot = _fresh_env(tmp_path)
    from services import whatsapp_client, painel

    async def _noop_send(*a, **k): return {"ok": True}
    monkeypatch.setattr(whatsapp_client, "send_message", _noop_send)

    calls = []
    async def fake_create_trial(**kwargs):
        calls.append(kwargs)
        return {"id": 43, "username": "test02new", "password": "abc",
                "expires_at": "2026-03-01"}
    monkeypatch.setattr(painel, "create_trial", fake_create_trial)

    async def go():
        await database.init_db()
        import aiosqlite
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO command_templates (id, name, trigger_command, "
                " requires_mac, system_type, response_template, enabled, "
                " created_at) "
                "VALUES ('t2', 'IPTV Teste', 'teste', 0, 'iptv', "
                "'✅ Ok {user}/{pass} {pay_link}', 1, ?)",
                (now,),
            )
            await db.commit()

        await bot.process_incoming_message(
            phone="555444333@lid",
            body="teste",
            from_me=False,
            name="LID Sem Numero",
            real_phone=None,  # Node couldn't resolve
        )
    _run(go())

    assert len(calls) == 1
    assert calls[0]["whatsapp"] == "", (
        f"Expected empty whatsapp for LID without real_phone, got {calls[0]!r}"
    )
