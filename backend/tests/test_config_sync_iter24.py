# Config sync (services/config_sync.py) ISOLATED tests: local throwaway Mongo + temp SQLite.
# NEVER touches Atlas: WHATSFLOW_MONGO_URL is blanked and the client host is asserted to be localhost.
import asyncio
import os
import sys
import tempfile
import uuid

import pytest

os.environ["WHATSFLOW_MONGO_URL"] = ""          # blank (survives load_dotenv, which doesn't override)
os.environ["WHATSFLOW_DB_NAME"] = ""
os.environ["MONGO_URL"] = "mongodb://localhost:27017"
os.environ["DB_NAME"] = f"TEST_cfgsync_{uuid.uuid4().hex[:8]}"
_TMP = tempfile.mkdtemp()
os.environ["SQLITE_PATH"] = os.path.join(_TMP, "boot.db")
sys.path.insert(0, "/app/backend")

import aiosqlite  # noqa: E402
import database  # noqa: E402
from services import mongo_store, config_sync  # noqa: E402

TEST_DB = os.environ["DB_NAME"]


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def _reset_mongo():
    os.environ["WHATSFLOW_MONGO_URL"] = ""
    mongo_store._client = None
    mongo_store._db = None


def _guard_db():
    db = mongo_store._get_db()
    assert db.name == TEST_DB, db.name
    host = str(mongo_store._client.address if False else os.environ["MONGO_URL"])
    assert "localhost" in host and not os.environ.get("WHATSFLOW_MONGO_URL")
    return db


async def _new_sqlite(name):
    path = os.path.join(_TMP, f"{name}_{uuid.uuid4().hex[:6]}.db")
    database.DB_PATH = path
    import routers.notifications as rn
    rn.DB_PATH = path
    await database.init_db()
    return path


async def _wipe_mongo():
    _reset_mongo()
    db = _guard_db()
    for c in ("config_settings", "config_notifications", "settings", "notification_templates", "command_templates"):
        await db[c].delete_many({})
    return db


async def _first_event_key():
    async with aiosqlite.connect(database.DB_PATH) as c:
        row = await (await c.execute("SELECT event_key FROM notification_templates ORDER BY event_key LIMIT 1")).fetchone()
    return row[0]


async def _local_body(ek):
    async with aiosqlite.connect(database.DB_PATH) as c:
        row = await (await c.execute("SELECT body FROM notification_templates WHERE event_key=?", (ek,))).fetchone()
    return row[0]


async def _put_notification(ek, body):
    from routers.notifications import update_notification as update_template
    import inspect
    sig = inspect.signature(update_template)
    model = list(sig.parameters.values())[1].annotation
    return await update_template(ek, model(body=body))


@pytest.fixture(autouse=True)
def primary_mode(monkeypatch):
    monkeypatch.delenv("CONFIG_SYNC_MODE", raising=False)
    yield


@pytest.fixture(scope="module", autouse=True)
def drop_test_db():
    yield
    async def _drop():
        _reset_mongo()
        db = _guard_db()
        await mongo_store._client.drop_database(TEST_DB)
    asyncio.run(_drop())


# ---------------- PRIMARY ----------------
class TestPrimary:
    def test_set_setting_writes_config_settings_and_skips_local_only(self):
        async def t():
            db = await _wipe_mongo()
            await _new_sqlite("p1")
            await database.set_setting("TEST_pix_key", "abc123")
            await database.set_setting("admin_password_hash", "TEST_hash")
            await database.set_setting("twofa_enabled", "1")
            d = await db.config_settings.find_one({"_id": "TEST_pix_key"})
            assert d and d["value"] == "abc123"
            assert await db.config_settings.find_one({"_id": "admin_password_hash"}) is None
            assert await db.config_settings.find_one({"_id": "twofa_enabled"}) is None
        run(t())

    def test_notification_put_writes_config_notifications(self):
        async def t():
            db = await _wipe_mongo()
            await _new_sqlite("p2")
            ek = await _first_event_key()
            await _put_notification(ek, "TEST_body_primary")
            d = await db.config_notifications.find_one({"_id": ek})
            assert d and d["body"] == "TEST_body_primary" and d["enabled"] in (0, 1)
            assert set(("title", "body", "image_url", "enabled")) <= set(d)
        run(t())

    def test_restore_defaults_writes_config_notifications(self):
        async def t():
            from routers.notifications import restore_default_template
            from services.default_templates import DEFAULT_TEMPLATES_BY_EVENT
            db = await _wipe_mongo()
            await _new_sqlite("p2b")
            ek = next(iter(DEFAULT_TEMPLATES_BY_EVENT))
            await _put_notification(ek, "TEST_custom")
            await restore_default_template(ek)
            d = await db.config_notifications.find_one({"_id": ek})
            assert d["body"] == DEFAULT_TEMPLATES_BY_EVENT[ek]["body"]
        run(t())

    def test_startup_pushes_all_local_config(self):
        async def t():
            db = await _wipe_mongo()
            await _new_sqlite("p3")
            async with aiosqlite.connect(database.DB_PATH) as c:
                await c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('TEST_direct','v1')")
                await c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('admin_password_hash','h')")
                n_settings = (await (await c.execute("SELECT count(*) FROM settings WHERE key NOT IN (%s)" %
                              ",".join("?" * len(config_sync.LOCAL_ONLY)), tuple(config_sync.LOCAL_ONLY))).fetchone())[0]
                n_notif = (await (await c.execute("SELECT count(*) FROM notification_templates")).fetchone())[0]
                await c.commit()
            await config_sync.sync_on_startup()
            assert (await db.config_settings.find_one({"_id": "TEST_direct"}))["value"] == "v1"
            assert await db.config_settings.find_one({"_id": "admin_password_hash"}) is None
            assert await db.config_settings.find_one({"_id": "config_restored"}) is None
            assert await db.config_settings.count_documents({}) >= n_settings
            assert await db.config_notifications.count_documents({}) == n_notif and n_notif > 0
            assert await database.get_setting("config_restored") == "1"
        run(t())

    def test_fresh_install_restores_from_atlas(self):
        async def t():
            db = await _wipe_mongo()
            await _new_sqlite("p4a")
            ek = await _first_event_key()
            await db.config_settings.insert_one({"_id": "TEST_restored_key", "value": "from_atlas"})
            await db.config_settings.insert_one({"_id": "admin_password_hash", "value": "ATLAS_HASH"})
            await db.config_notifications.insert_one({"_id": ek, "title": "T", "body": "TEST_atlas_body",
                                                      "image_url": "", "enabled": 1})
            await _new_sqlite("p4_fresh")  # fresh DB, config_restored absent
            await database.set_setting("admin_password_hash", "LOCAL_HASH")
            assert await database.get_setting("config_restored") == ""
            await config_sync.sync_on_startup()
            assert await database.get_setting("TEST_restored_key") == "from_atlas"
            assert await _local_body(ek) == "TEST_atlas_body"
            assert await database.get_setting("admin_password_hash") == "LOCAL_HASH"
            assert await database.get_setting("config_restored") == "1"
        run(t())

    def test_existing_install_local_wins_and_pushes(self):
        async def t():
            db = await _wipe_mongo()
            await _new_sqlite("p5")
            ek = await _first_event_key()
            await database.set_setting("TEST_k", "local_v")
            await database.set_setting("config_restored", "1")
            await db.config_settings.update_one({"_id": "TEST_k"}, {"$set": {"value": "atlas_v"}})
            await db.config_notifications.update_one({"_id": ek}, {"$set": {"body": "atlas_body"}}, upsert=True)
            local_body = await _local_body(ek)
            await config_sync.sync_on_startup()
            assert await database.get_setting("TEST_k") == "local_v"
            assert (await db.config_settings.find_one({"_id": "TEST_k"}))["value"] == "local_v"
            assert (await db.config_notifications.find_one({"_id": ek}))["body"] == local_body
        run(t())


# ---------------- REPLICA ----------------
class TestReplica:
    def test_saves_do_not_write_atlas(self, monkeypatch):
        async def t():
            db = await _wipe_mongo()
            await _new_sqlite("r1")
            monkeypatch.setenv("CONFIG_SYNC_MODE", "replica")
            ek = await _first_event_key()
            await database.set_setting("TEST_rep", "x")
            await _put_notification(ek, "TEST_rep_body")
            from routers.notifications import restore_default_template
            from services.default_templates import DEFAULT_TEMPLATES_BY_EVENT
            await restore_default_template(next(iter(DEFAULT_TEMPLATES_BY_EVENT)))
            await mongo_store.upsert_command_template({"id": "TEST_cmd", "name": "x"})
            await mongo_store.sync_command_templates()
            assert await database.get_setting("TEST_rep") == "x"
            assert await _local_body(ek) == "TEST_rep_body"
            for c in ("config_settings", "config_notifications", "settings", "notification_templates", "command_templates"):
                assert await db[c].count_documents({}) == 0, c
        run(t())

    def test_startup_pulls_atlas_but_keeps_local_only(self, monkeypatch):
        async def t():
            db = await _wipe_mongo()
            await _new_sqlite("r2")
            ek = await _first_event_key()
            await database.set_setting("TEST_pull", "local_v")
            await database.set_setting("admin_password_hash", "LOCAL_HASH")
            await database.set_setting("legacy_password_login", "0")
            await db.config_settings.delete_many({})
            await db.config_notifications.delete_many({})
            await db.config_settings.insert_many([
                {"_id": "TEST_pull", "value": "atlas_v"},
                {"_id": "admin_password_hash", "value": "ATLAS_HASH"},
                {"_id": "legacy_password_login", "value": "1"}])
            await db.config_notifications.insert_one({"_id": ek, "title": "t", "body": "atlas_rep_body",
                                                      "image_url": "", "enabled": 0})
            monkeypatch.setenv("CONFIG_SYNC_MODE", "replica")
            await database.set_setting("config_restored", "1")
            await config_sync.sync_on_startup()
            assert await database.get_setting("TEST_pull") == "atlas_v"
            assert await _local_body(ek) == "atlas_rep_body"
            assert await database.get_setting("admin_password_hash") == "LOCAL_HASH"
            assert await database.get_setting("legacy_password_login") == "0"
            st = await config_sync.status()
            assert st["mode"] == "replica" and st["settings_in_atlas"] == 3
        run(t())
