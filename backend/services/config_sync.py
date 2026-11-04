"""Durable config in Mongo Atlas.

The live install (primary, default) owns the config: every save goes to Atlas
(`config_settings`, `config_notifications`) and on startup the whole local
config is pushed. A fresh/reinstalled primary restores from Atlas first.
A preview/dev install (CONFIG_SYNC_MODE=replica) never writes config to Atlas;
it only copies the live config down, so testing here can't overwrite production.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

import aiosqlite

logger = logging.getLogger(__name__)

# Login/2FA keys stay per-install: a replica keeps its own access.
LOCAL_ONLY = {"admin_password_hash", "admin_password_seed_fp", "supabase_admin_email", "supabase_totp_enabled",
              "legacy_password_login", "twofa_enabled", "twofa_email", "config_restored"}
NOTIF_COLS = ("title", "body", "image_url", "enabled")
PULL_INTERVAL = 600


def is_replica() -> bool:
    return os.environ.get("CONFIG_SYNC_MODE", "primary").strip().lower() == "replica"


def _db():
    from services.mongo_store import _get_db
    return _get_db()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def save_setting(key: str, value: str):
    if is_replica() or key in LOCAL_ONLY:
        return
    try:
        await _db().config_settings.update_one({"_id": key}, {"$set": {"value": value, "updated_at": _now()}}, upsert=True)
    except Exception as e:
        logger.warning("config_settings save failed for %s: %s", key, e)


async def save_notification(t: dict):
    if is_replica() or not t.get("event_key"):
        return
    try:
        doc = {c: t.get(c) for c in NOTIF_COLS}
        doc["enabled"] = 1 if t.get("enabled") else 0
        await _db().config_notifications.update_one({"_id": t["event_key"]}, {"$set": {**doc, "updated_at": _now()}}, upsert=True)
    except Exception as e:
        logger.warning("config_notifications save failed for %s: %s", t.get("event_key"), e)


async def _pull(conn) -> tuple[int, int]:
    """Atlas → local (Atlas wins). Returns (settings, notifications) applied."""
    db = _db()
    s_n = n_n = 0
    async for d in db.config_settings.find({}):
        if d["_id"] in LOCAL_ONLY:
            continue
        await conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                           (d["_id"], d.get("value") or ""))
        s_n += 1
    async for d in db.config_notifications.find({}):
        cur = await conn.execute(
            "UPDATE notification_templates SET title = ?, body = ?, image_url = ?, enabled = ?, updated_at = ? WHERE event_key = ?",
            (d.get("title") or "", d.get("body") or "", d.get("image_url") or "", int(d.get("enabled") or 0),
             d.get("updated_at") or _now(), d["_id"]))
        n_n += cur.rowcount
    await conn.commit()
    return s_n, n_n


async def _push(conn):
    db = _db()
    conn.row_factory = aiosqlite.Row
    rows = await (await conn.execute("SELECT key, value FROM settings")).fetchall()
    for r in rows:
        if r["key"] not in LOCAL_ONLY:
            await db.config_settings.update_one({"_id": r["key"]}, {"$set": {"value": r["value"], "updated_at": _now()}}, upsert=True)
    notifs = await (await conn.execute("SELECT * FROM notification_templates")).fetchall()
    for t in notifs:
        await save_notification(dict(t))
    return len(rows), len(notifs)


async def sync_on_startup():
    from database import DB_PATH, get_setting, set_setting
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            if is_replica():
                logger.info("config sync (replica): pulled %s from Atlas", await _pull(conn))
                return
            if await get_setting("config_restored") != "1" and await _db().config_settings.estimated_document_count():
                logger.info("config sync: restored %s from Atlas (fresh install)", await _pull(conn))
            logger.info("config sync (primary): pushed %s to Atlas", await _push(conn))
        await set_setting("config_restored", "1")
    except Exception as e:
        logger.warning("config sync on startup failed: %s", e)


async def replica_pull_loop():
    from database import DB_PATH
    while is_replica():
        await asyncio.sleep(PULL_INTERVAL)
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await _pull(conn)
        except Exception as e:
            logger.warning("config replica pull failed: %s", e)


async def status() -> dict:
    db = _db()
    return {"mode": "replica" if is_replica() else "primary",
            "settings_in_atlas": await db.config_settings.estimated_document_count(),
            "notifications_in_atlas": await db.config_notifications.estimated_document_count()}
