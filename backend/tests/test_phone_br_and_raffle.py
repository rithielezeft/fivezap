# Iteration 10: BR phone normalization (9th digit) + Trevo da Sorte raffle (API + draw logic, mocked side effects)
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PASSWORD = "Rithi0518@"


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}")
    tok = r.json().get("token") or r.json().get("access_token")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


# ---------- Phone normalization (pure functions) ----------
class TestPhoneNormalization:
    def test_clean_plus_old_format(self):
        from services.phone_extractor import _clean
        assert _clean("+55 31 8658-2251") == "5531986582251"

    def test_clean_bare_12(self):
        from services.phone_extractor import _clean
        assert _clean("553186582251") == "5531986582251"

    def test_clean_bare_10_local(self):
        from services.phone_extractor import _clean
        assert _clean("(31) 8658-2251") == "5531986582251"

    def test_landline_unchanged(self):
        from services.phone_extractor import _clean
        assert _clean("553133334444") == "553133334444"

    def test_already_canonical(self):
        from services.phone_extractor import _clean
        assert _clean("5531986582251") == "5531986582251"

    def test_foreign_untouched(self):
        from services.phone_extractor import _clean
        assert _clean("+34 612 345 678") == "34612345678"
        assert _clean("+1 (555) 123-4567") == "15551234567"

    def test_normalize_phone_jid(self):
        from services.bot import normalize_phone
        assert normalize_phone("553186582251@c.us") == "5531986582251"
        assert normalize_phone("123456789012345@lid") == "123456789012345@lid"

    def test_br_variants(self):
        from services.phone_extractor import br_variants
        v = br_variants("5531986582251")
        assert set(v) == {"5531986582251", "553186582251"}
        assert br_variants("553186582251")[0] == "5531986582251"


# ---------- find_or_create_customer legacy upgrade (temp row) ----------
def test_find_or_create_upgrades_legacy_row():
    import aiosqlite
    from database import DB_PATH
    from services.bot import find_or_create_customer
    cid = "TEST_" + uuid.uuid4().hex[:8]
    legacy, canon = "559998765432", "5599998765432"  # fake DDD 99 number

    async def run():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM customers WHERE whatsapp IN (?,?)", (legacy, canon))
            await db.execute("INSERT INTO customers (id,name,whatsapp,system_type,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                             (cid, "TEST_Legacy", legacy, "iptv", "prospect", "2026-01-01", "2026-01-01"))
            await db.commit()
        try:
            got = await find_or_create_customer(canon)
            async with aiosqlite.connect(DB_PATH) as db:
                row = await (await db.execute("SELECT whatsapp FROM customers WHERE id=?", (cid,))).fetchone()
                n = await (await db.execute("SELECT COUNT(*) FROM customers WHERE whatsapp IN (?,?)", (legacy, canon))).fetchone()
            return got, row, n
        finally:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM customers WHERE id=? OR whatsapp IN (?,?)", (cid, legacy, canon))
                await db.commit()

    got, row, n = asyncio.run(run())
    assert got["id"] == cid
    assert row[0] == canon
    assert n[0] == 1


# ---------- Public trial validation ----------
def test_public_trial_short_number_400():
    r = requests.post(f"{BASE_URL}/api/public/trial", json={"name": "TEST", "whatsapp": "8658-2251", "system_type": "iptv"})
    assert r.status_code == 400, r.text
    assert "inválido" in r.json().get("detail", "")


# ---------- Raffle API ----------
class TestRaffleApi:
    def test_public_raffle_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/public/raffle")
        assert r.status_code == 200
        d = r.json()
        for k in ("enabled", "clover_cents", "prize_months", "max_clovers", "participants", "draw_at"):
            assert k in d

    def test_admin_raffle_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/raffle").status_code == 401
        assert requests.post(f"{BASE_URL}/api/raffle/draw").status_code == 401
        assert requests.put(f"{BASE_URL}/api/raffle/settings", json={"enabled": True}).status_code == 401

    def test_overview_and_settings_persist(self, admin):
        r = admin.put(f"{BASE_URL}/api/raffle/settings",
                      json={"enabled": False, "clover_price": "2,50", "prize_months": 3, "joker_login": ""})
        assert r.status_code == 200
        assert r.json()["clover_cents"] == 250 and r.json()["prize_months"] == 3
        g = admin.get(f"{BASE_URL}/api/raffle").json()
        assert g["config"]["clover_cents"] == 250 and g["config"]["prize_months"] == 3
        assert g["config"]["enabled"] is False
        assert isinstance(g["history"], list) and isinstance(g["entries"], list)
        # invalid prize months -> coerced to 1
        r = admin.put(f"{BASE_URL}/api/raffle/settings", json={"prize_months": 7})
        assert r.json()["prize_months"] == 1
        admin.put(f"{BASE_URL}/api/raffle/settings", json={"clover_price": "2,00", "prize_months": 1})

    def test_draw_without_clovers_400(self, admin):
        if admin.get(f"{BASE_URL}/api/raffle").json()["clovers"]:
            pytest.skip("real clovers exist - not drawing")
        r = admin.post(f"{BASE_URL}/api/raffle/draw")
        assert r.status_code == 400
        assert r.json()["detail"] == "Nenhum trevo pago neste mês"


# ---------- Draw logic with mocked renewal + notifier ----------
def test_perform_draw_mocked():
    import aiosqlite
    from database import DB_PATH, set_setting
    from services import raffle, painel, notifier

    calls = {"renew": [], "admin": [], "hard": []}

    async def fake_renew(**kw):
        calls["renew"].append(kw)
        return {"ok": True}

    async def fake_admin(msg, *a, **k):
        calls["admin"].append(msg)

    async def fake_hard(phone, msg, *a, **k):
        calls["hard"].append((phone, msg))

    pid = "TEST_" + uuid.uuid4().hex[:8]

    async def run():
        from services.mongo_store import _get_db
        orig = (painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded)
        painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded = fake_renew, fake_admin, fake_hard
        month, _, _ = await raffle.month_bounds()
        try:
            await set_setting("raffle_joker_login", "TEST_joker")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, created_at, paid_at, clovers) "
                                 "VALUES (?,?,?,?,?,?,?,?,?)", (pid, "TEST_cust", 1, 3600, 17, "paid",
                                                                datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), 3))
                await db.commit()
            ent = await raffle.entries()
            res = await raffle.perform_draw()
            second = None
            try:
                await raffle.perform_draw()
            except ValueError as e:
                second = str(e)
            hist = await raffle.history(1)
            return ent, res, second, hist
        finally:
            painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded = orig
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM payments WHERE id=?", (pid,))
                await db.commit()
            await _get_db().payments.delete_many({"id": pid})
            await _get_db().raffle_draws.delete_one({"_id": month})
            await set_setting("raffle_joker_login", "")

    ent, res, second, hist = asyncio.run(run())
    assert ent["clovers"] == 3 and ent["participants"] == 1
    assert len(ent["pool"]) == 4 and ent["pool"][-1].get("joker") is True
    assert res["status"] == "drawn" and res["renewed"] is True
    assert res["sequence"][res["win_index"]]["coupon"] == res["winner"]["coupon"]
    assert len(calls["renew"]) == 1 and len(calls["admin"]) == 1
    assert second and "já foi realizado" in second
    assert hist and hist[0]["month"] == res["month"]
