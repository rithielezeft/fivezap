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
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db = None


def _get_db():
    """Lazy-init the MongoDB client & database. Reads config from env each
    call (so tests can monkeypatch MONGO_URL/DB_NAME freely)."""
    global _client, _db
    if _db is not None:
        return _db
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "whatsflow")
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


async def ping() -> bool:
    """Health check — returns True if Atlas is reachable."""
    try:
        db = _get_db()
        r = await db.command("ping")
        return bool(r.get("ok"))
    except Exception as e:
        logger.warning("mongo ping failed: %s", e)
        return False
