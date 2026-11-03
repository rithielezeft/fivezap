"""MongoDB Atlas persistence layer for customers/trials.

Motivation: SQLite lives only on the Raspberry Pi. When customers open
`/pay/{painel_id}` from anywhere in the world, the request lands on
whatever host is serving the frontend — which may not have the same
SQLite file. Using MongoDB Atlas gives all environments (Raspberry Pi,
preview, prod) a single shared source of truth for /pay/{id} lookups.

Schema (customers collection, _id = painel user id as string):
    {
      "_id": "228116806",            # painel user id (STRING)
      "id": 228116806,               # numeric copy for legacy queries
      "painel_username": "oscarnew", # login
      "painel_password": "abc",      # for admin panel display
      "full_name": "Nome do cliente",
      "whatsapp": "5511999999999",
      "system_type": "p2p" | "iptv" | "hybrid",
      "exp_date_iso": "2026-08-15T16:20:52+00:00",
      "is_trial": true,
      "mac": "AA:BB:CC:DD:EE:FF" or None,
      "last_synced_at": iso timestamp
    }
"""
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db = None


def _clean_url(raw: Optional[str]) -> Optional[str]:
    """Accept values pasted as a whole .env line (MONGO_URL="...") or cut off
    by a terminal ('...retryWrites=tru>'): keep only a valid mongodb URI."""
    if not raw:
        return None
    v = re.sub(r"^\s*[A-Z_]+\s*=\s*", "", raw).strip().strip("\"'").rstrip(">")
    if "?" in v:
        base, query = v.split("?", 1)
        ok = all(re.fullmatch(r"\w+=(true|false|majority|\d+|[\w.-]+)", p) for p in query.split("&") if p)
        if not ok or "retryWrites=tru" in query and "retryWrites=true" not in query:
            v = base + "?retryWrites=true&w=majority"
    return v if v.startswith(("mongodb://", "mongodb+srv://")) else None


def _get_db():
    """Lazy-init the MongoDB client & database. Reads config from env each
    call (so tests can monkeypatch MONGO_URL/DB_NAME freely)."""
    global _client, _db
    if _db is not None:
        return _db
    # The user's own Atlas cluster (shared with the Raspberry) wins over the
    # platform-provided MONGO_URL when configured.
    mongo_url = _clean_url(os.environ.get("WHATSFLOW_MONGO_URL")) or os.environ.get("MONGO_URL")
    db_name = (os.environ.get("WHATSFLOW_DB_NAME") if os.environ.get("WHATSFLOW_MONGO_URL")
               else None) or os.environ.get("DB_NAME", "whatsflow")
    if not mongo_url:
        raise RuntimeError("MONGO_URL not set")
    _client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=8000)
    _db = _client[db_name]
    return _db


async def find_customer_by_painel_id(painel_id: str) -> Optional[dict]:
    """Look up a customer by painel user id (matches `_id` or numeric `id`).

    Returns the Mongo document (with `_id` stringified) or None.
    """
    if not painel_id:
        return None
    try:
        db = _get_db()
    except Exception as e:
        logger.warning("mongo_store: db init failed: %s", e)
        return None

    pid_str = str(painel_id)
    # Try string _id first (new format), then numeric id (legacy)
    doc = await db.customers.find_one({"_id": pid_str})
    if not doc:
        try:
            pid_int = int(pid_str)
            doc = await db.customers.find_one({"id": pid_int})
        except ValueError:
            pass
    if not doc:
        # Also try painel_username as fallback
        doc = await db.customers.find_one({"username": pid_str}) \
              or await db.customers.find_one({"painel_username": pid_str})
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc


async def upsert_customer(customer: dict) -> Optional[str]:
    """Save/update a customer in Mongo. `customer` must include a `painel_id`,
    `id`, or `_id`. Returns the resolved `_id` (painel id as string) or None
    if we couldn't determine an identity.

    Called right after every trial creation so /pay/{painel_id} works
    globally from any environment immediately.
    """
    try:
        db = _get_db()
    except Exception as e:
        logger.warning("mongo_store: db init failed: %s", e)
        return None

    pid = customer.get("_id") or customer.get("painel_id") or customer.get("id")
    if pid is None:
        logger.warning("mongo_store.upsert_customer: no painel id in %s", customer)
        return None
    pid_str = str(pid)

    doc = {**customer}
    doc["_id"] = pid_str
    try:
        doc["id"] = int(pid_str)
    except (ValueError, TypeError):
        pass
    doc.setdefault("last_synced_at", datetime.now(timezone.utc).isoformat())
    # Never overwrite _id via $set
    to_set = {k: v for k, v in doc.items() if k != "_id"}

    try:
        await db.customers.update_one(
            {"_id": pid_str},
            {"$set": to_set},
            upsert=True,
        )
        return pid_str
    except Exception as e:
        logger.exception("mongo_store.upsert_customer failed for %s: %s", pid_str, e)
        return None


async def upsert_payment(payment: dict) -> Optional[str]:
    """Save/update a payment record in Mongo Atlas (`payments` collection).

    `_id` = local payment UUID (so we can idempotently update the same record
    when status changes from pending → paid → renewed).
    """
    try:
        db = _get_db()
    except Exception as e:
        logger.warning("mongo_store: db init failed: %s", e)
        return None

    pid = payment.get("_id") or payment.get("id") or payment.get("payment_id")
    if not pid:
        logger.warning("mongo_store.upsert_payment: no id in payment doc")
        return None
    pid_str = str(pid)

    doc = {**payment}
    doc["_id"] = pid_str
    doc.setdefault("last_synced_at", datetime.now(timezone.utc).isoformat())
    to_set = {k: v for k, v in doc.items() if k != "_id"}

    try:
        await db.payments.update_one(
            {"_id": pid_str},
            {"$set": to_set},
            upsert=True,
        )
        return pid_str
    except Exception as e:
        logger.exception("mongo_store.upsert_payment failed for %s: %s", pid_str, e)
        return None


async def ping() -> bool:
    """Health check — returns True if Atlas is reachable."""
    try:
        db = _get_db()
        r = await db.command("ping")
        return bool(r.get("ok"))
    except Exception as e:
        logger.warning("mongo ping failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Settings & templates sync to Atlas
# ---------------------------------------------------------------------------

async def upsert_setting(key: str, value: str) -> bool:
    """Mirror a single setting from SQLite → Atlas.

    Atlas collection `settings` — same shape as SQLite: {_id: key, value}.
    Called from database.set_setting on every write. Best-effort.
    """
    try:
        db = _get_db()
        await db.settings.update_one(
            {"_id": key},
            {"$set": {
                "value": value,
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning("upsert_setting failed for %s: %s", key, e)
        return False


async def upsert_template(template: dict) -> bool:
    """Mirror a notification_templates row → Atlas.

    Called from the templates router on create/update/delete. Best-effort.
    """
    tid = template.get("id") or template.get("event_key")
    if not tid:
        return False
    try:
        db = _get_db()
        await db.notification_templates.update_one(
            {"_id": str(tid)},
            {"$set": {
                **template,
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning("upsert_template failed for %s: %s", tid, e)
        return False


async def upsert_command_template(t: dict) -> bool:
    """Mirror a command_templates row (Comandos page) → Atlas `command_templates`."""
    try:
        await _get_db().command_templates.update_one(
            {"_id": str(t["id"])}, {"$set": {**t, "last_synced_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        return True
    except Exception as e:
        logger.warning("upsert_command_template failed for %s: %s", t.get("id"), e)
        return False


async def delete_command_template(template_id: str) -> bool:
    try:
        await _get_db().command_templates.delete_one({"_id": str(template_id)})
        return True
    except Exception as e:
        logger.warning("delete_command_template failed for %s: %s", template_id, e)
        return False


async def sync_command_templates():
    """Startup: push local commands to Atlas and restore commands that exist only in Atlas."""
    import aiosqlite
    from database import DB_PATH
    cols = ("id", "name", "trigger_command", "system_type", "requires_mac", "package_id",
            "response_template", "image_url", "enabled", "trigger_source", "created_at")
    try:
        db_m = _get_db()
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            local = [dict(r) for r in await (await db.execute("SELECT * FROM command_templates")).fetchall()]
            for t in local:
                await upsert_command_template(t)
            triggers = {t["trigger_command"].strip().lower() for t in local}
            ids = {t["id"] for t in local}
            restored = 0
            async for d in db_m.command_templates.find({}):
                if d.get("id") in ids or (d.get("trigger_command") or "").strip().lower() in triggers:
                    continue
                await db.execute(f"INSERT OR IGNORE INTO command_templates ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                 tuple(d.get(c) for c in cols))
                restored += 1
            await db.commit()
        logger.info("command templates synced with Atlas: pushed %d, restored %d", len(local), restored)
    except Exception as e:
        logger.warning("sync_command_templates failed: %s", e)


async def delete_template(template_id: str) -> bool:
    try:
        db = _get_db()
        await db.notification_templates.delete_one({"_id": str(template_id)})
        return True
    except Exception as e:
        logger.warning("delete_template failed for %s: %s", template_id, e)
        return False
