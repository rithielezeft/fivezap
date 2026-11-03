# Iter23 — ISOLATED unit tests: multi-login checkout → all logins renewed, ONE client msg, ONE admin msg.
# Safety: temp SQLite, local throwaway Mongo, painel/notifier fully monkeypatched. Never touches live services.
import os
import sys
import tempfile
import asyncio
import json
import uuid

_TMP = tempfile.mkdtemp()
os.environ["SQLITE_PATH"] = os.path.join(_TMP, "iter23.db")
os.environ.pop("WHATSFLOW_MONGO_URL", None)
os.environ.pop("WHATSFLOW_DB_NAME", None)
os.environ["MONGO_URL"] = "mongodb://localhost:27017"
os.environ["DB_NAME"] = "TEST_iter23_throwaway"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
import aiosqlite  # noqa: E402
import database  # noqa: E402
from services import mongo_store, painel, notifier  # noqa: E402
from services import default_templates  # noqa: E402
import routers.payments as pay  # noqa: E402
import routers.painel_users as pu  # noqa: E402
from services import renewal_retry  # noqa: E402

DB = os.environ["SQLITE_PATH"]
MAIN, X1, X2 = "900000001", "900000002", "900000003"
USERS = {MAIN: {"id": MAIN, "username": "TEST_main", "password": "p"},
         X1: {"id": X1, "username": "TEST_extra1"},
         X2: {"id": X2, "username": "TEST_extra2"}}
MULTI_TPL = next(t for t in default_templates.DEFAULT_TEMPLATES if t["event_key"] == "renewal_success_multi") \
    if hasattr(default_templates, "DEFAULT_TEMPLATES") else None


def _patch_db_paths(monkeypatch):
    for name, mod in list(sys.modules.items()):
        if mod is not None and getattr(mod, "DB_PATH", None) and (name.startswith(("routers", "services")) or name == "database"):
            monkeypatch.setattr(mod, "DB_PATH", DB, raising=False)


@pytest.fixture
def env(monkeypatch):
    assert database.DB_PATH == DB
    _patch_db_paths(monkeypatch)
    monkeypatch.setattr(mongo_store, "_client", None, raising=False)
    monkeypatch.setattr(mongo_store, "_db", None, raising=False)
    asyncio.run(database.init_db())
    cap = {"renew": [], "notif": [], "hard": [], "admin": [], "fail": set(), "tpl_enabled": True}

    async def fake_renew(user_id, package_id, months=None, adult=None, **kw):
        cap["renew"].append(str(user_id))
        if str(user_id) in cap["fail"]:
            raise RuntimeError("ERROR_NO_SLOT_AVAILABLE")
        return {"expires_at": {MAIN: "2026-03-10", X1: "2026-04-11", X2: "2026-05-12"}.get(str(user_id), "2026-06-01")}

    async def fake_notif(event_key, phone, ctx, customer_id=None, **kw):
        cap["notif"].append({"event": event_key, "phone": phone, "ctx": ctx,
                             "at_renew_count": len(cap["renew"])})
        return cap["tpl_enabled"]

    async def fake_hard(phone, body, event_key="hardcoded", customer_id=None):
        cap["hard"].append({"event": event_key, "phone": phone, "body": body, "at_renew_count": len(cap["renew"])})
        return True

    async def fake_admin(message):
        cap["admin"].append(message)
        return True

    async def fake_cache_user(pid):
        return USERS.get(str(pid), {})

    async def fake_read_cache():
        return list(USERS.values()), None

    async def noop(*a, **k):
        return 0

    monkeypatch.setattr(painel, "renew_user", fake_renew)
    monkeypatch.setattr(notifier, "send_notification", fake_notif)
    monkeypatch.setattr(notifier, "send_hardcoded", fake_hard)
    monkeypatch.setattr(notifier, "send_admin_alert", fake_admin)
    monkeypatch.setattr(pay, "_cache_user", fake_cache_user)
    monkeypatch.setattr(pu, "_read_cache", fake_read_cache)
    import services.reminders as rem
    monkeypatch.setattr(rem, "cancel_pending_for_phone", noop)
    yield cap


async def _seed(extras, status="pending", nsu=None):
    pid = "TEST_" + uuid.uuid4().hex[:10]
    nsu = nsu or f"trial-{MAIN}-1m-{uuid.uuid4().hex[:6]}"
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO customers (id, name, whatsapp, system_type, painel_username, created_at, updated_at)"
                         " VALUES (?, 'TEST Cliente', '5511900000099', 'iptv', 'TEST_main', '2026-01-01', '2026-01-01')", (MAIN,))
        await db.execute("INSERT INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, order_nsu,"
                         " extra_customer_ids, created_at) VALUES (?, ?, 1, 9000, 42, ?, ?, ?, '2026-01-01')",
                         (pid, MAIN, status, nsu, json.dumps(extras) if extras is not None else None))
        await db.commit()
    return pid, nsu


def _confirm(nsu):
    return asyncio.run(pay._process_payment_confirmation(nsu, True, source="TEST", raw={}))


# --- Multi-login happy path
def test_multi_all_renewed_single_client_and_admin_msg(env):
    _, nsu = asyncio.run(_seed([X1, X2]))
    res = _confirm(nsu)
    assert res["status"] == "renewed", res
    assert env["renew"] == [MAIN, X1, X2]
    assert len(env["notif"]) == 1 and not env["hard"], (env["notif"], env["hard"])
    n = env["notif"][0]
    assert n["event"] == "renewal_success_multi"
    assert n["at_renew_count"] == 3, "client msg sent before all renewals"
    assert n["ctx"]["count"] == 3
    logins = n["ctx"]["logins"]
    assert "• *TEST_main* — ativo até 10/03/2026" in logins
    assert "• *TEST_extra1* — ativo até 11/04/2026" in logins
    assert "• *TEST_extra2* — ativo até 12/05/2026" in logins
    assert not any(x["event"] == "renewal_success" for x in env["notif"])
    assert len(env["admin"]) == 1
    a = env["admin"][0]
    assert "Logins no pagamento: 3" in a
    assert "✅ TEST_main — novo vencimento 10/03/2026" in a
    assert "✅ TEST_extra1 — novo vencimento 11/04/2026" in a
    assert "✅ TEST_extra2 — novo vencimento 12/05/2026" in a
    assert "Cliente notificado: sim (mensagem única" in a
    if MULTI_TPL:
        body = MULTI_TPL["body"].format_map({**n["ctx"]})
        assert "TEST_extra2" in body and "{" not in body
    print("CLIENT CTX logins:\n" + logins + "\nADMIN:\n" + a)


# --- Template disabled → single hardcoded fallback
def test_multi_template_disabled_fallback_single(env):
    env["tpl_enabled"] = False
    _, nsu = asyncio.run(_seed([X1]))
    _confirm(nsu)
    assert env["renew"] == [MAIN, X1]
    client_msgs = [x for x in env["notif"]] + env["hard"]
    assert len(client_msgs) == 2  # 1 attempted template (returned False) + 1 fallback
    assert [h["event"] for h in env["hard"]] == ["renewal_success_multi_fallback"]
    body = env["hard"][0]["body"]
    assert "*2 logins*" in body and "TEST_extra1" in body and "11/04/2026" in body
    assert len(env["admin"]) == 1 and "mensagem padrão única" in env["admin"][0]


# --- One extra fails
def test_multi_one_extra_fails(env):
    env["fail"].add(X2)
    _, nsu = asyncio.run(_seed([X1, X2]))
    res = _confirm(nsu)
    assert res["status"] == "renewed"
    assert env["renew"] == [MAIN, X1, X2]
    assert len(env["notif"]) == 1 and not env["hard"]
    logins = env["notif"][0]["ctx"]["logins"]
    assert "• *TEST_extra2* — nossa equipe vai concluir a renovação em breve" in logins
    assert "TEST_extra1* — ativo até 11/04/2026" in logins
    assert len(env["admin"]) == 1
    a = env["admin"][0]
    assert "❌ TEST_extra2 — FALHOU (ERROR_NO_SLOT_AVAILABLE) · renove manualmente" in a
    print("ADMIN (fail):\n" + a)


# --- Single-login keeps old behaviour
def test_single_login_unchanged(env):
    _, nsu = asyncio.run(_seed(None))
    _confirm(nsu)
    assert env["renew"] == [MAIN]
    assert [n["event"] for n in env["notif"]] == ["renewal_success"]
    assert env["notif"][0]["ctx"]["new_expires_at"] == "10/03/2026"
    assert not env["hard"]
    assert len(env["admin"]) == 1 and "Logins no pagamento" not in env["admin"][0]
    assert "Cliente notificado: sim (template)" in env["admin"][0]


def test_single_login_empty_list_unchanged(env):
    _, nsu = asyncio.run(_seed([]))
    _confirm(nsu)
    assert env["renew"] == [MAIN]
    assert [n["event"] for n in env["notif"]] == ["renewal_success"]
    assert len(env["admin"]) == 1 and "Logins no pagamento" not in env["admin"][0]


# --- Idempotency: second confirmation does not re-send
def test_multi_idempotent_second_confirmation(env):
    _, nsu = asyncio.run(_seed([X1]))
    _confirm(nsu)
    r2 = _confirm(nsu)
    assert r2["status"] == "already_processed"
    assert env["renew"] == [MAIN, X1]
    assert len(env["notif"]) == 1 and len(env["admin"]) == 1


# --- Auto-retry path
def test_retry_path_multi(env):
    pid, nsu = asyncio.run(_seed([X1, X2], status="paid_renewal_failed"))

    async def mark_due():
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE payments SET renewal_next_retry_at='2000-01-01T00:00:00+00:00', renewal_attempts=1 WHERE id=?", (pid,))
            await db.commit()
    asyncio.run(mark_due())
    asyncio.run(renewal_retry._sweep_once())
    assert env["renew"][:3] == [MAIN, X1, X2], env["renew"]
    assert len(env["notif"]) == 1 and env["notif"][0]["event"] == "renewal_success_multi"
    assert env["notif"][0]["at_renew_count"] >= 3
    logins = env["notif"][0]["ctx"]["logins"]
    assert "TEST_main* — ativo até 10/03/2026" in logins and "TEST_extra2* — ativo até 12/05/2026" in logins
    admin = [a for a in env["admin"] if "auto-retry" in a]
    assert len(admin) == 1 and "Logins no pagamento: 3" in admin[0]
    print("RETRY ADMIN:\n" + admin[0])


def test_main_fails_extras_not_renewed_no_success_msg(env):
    env["fail"].add(MAIN)
    _, nsu = asyncio.run(_seed([X1]))
    _confirm(nsu)
    assert env["renew"] == [MAIN]
    assert not any(n["event"] in ("renewal_success", "renewal_success_multi") for n in env["notif"])
