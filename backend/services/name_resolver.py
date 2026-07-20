"""Cascading customer-name resolver.

Rule: **never fall back to the generic word "cliente"** while there's a real
name available somewhere. Cascade:
    1. Local SQLite `customers.name`
    2. MongoDB Atlas (`mongo_store.find_customer_by_painel_id`)
    3. painel.fun users cache (fields: full_name, name, customer_name, username)
    4. As a last resort, the caller-provided `fallback` (default "cliente")

Whichever source we resolve from, we also opportunistically persist the name
back to SQLite so future lookups are instant and the Clientes page is right.
"""
from __future__ import annotations

import logging
from typing import Optional

import aiosqlite

import database
from models import now_iso

logger = logging.getLogger(__name__)


def _pick_name(u: dict) -> str:
    """Best-effort name extraction from a painel.fun user dict."""
    if not isinstance(u, dict):
        return ""
    for key in ("full_name", "name", "customer_name", "display_name", "username", "login"):
        v = u.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


async def resolve_customer_name(customer_id: str, fallback: str = "cliente") -> str:
    """Return the real client name from wherever we can find it.

    NEVER returns an empty string — falls back to `fallback` only when nothing
    else is available.
    """
    cid = str(customer_id or "").strip()
    if not cid:
        return fallback

    # 1) SQLite
    try:
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT name FROM customers WHERE id = ?", (cid,))
            row = await cur.fetchone()
            if row and (row["name"] or "").strip():
                return row["name"].strip()
    except Exception:
        logger.exception("resolve_customer_name: SQLite lookup failed for %s", cid)

    # 2) Mongo
    try:
        from services import mongo_store
        mdoc = await mongo_store.find_customer_by_painel_id(cid)
        if mdoc:
            for key in ("name", "full_name", "customer_name"):
                v = (mdoc.get(key) or "").strip()
                if v:
                    await _persist_name(cid, v)
                    return v
    except Exception:
        logger.exception("resolve_customer_name: Mongo lookup failed for %s", cid)

    # 3) painel.fun cache — the source of truth
    try:
        from routers.painel_users import _read_cache
        users, _ = await _read_cache()
        for u in users:
            uid = str(u.get("id") or u.get("user_id") or u.get("username") or "").strip()
            if uid == cid:
                name = _pick_name(u)
                if name:
                    await _persist_name(cid, name)
                    return name
                break
    except Exception:
        logger.exception("resolve_customer_name: painel cache lookup failed for %s", cid)

    return fallback


async def _persist_name(customer_id: str, name: str):
    """Upsert the resolved name into local `customers` so we don't hit the
    cascade next time. Keeps updated_at fresh so the Clientes page reflects
    the change immediately."""
    if not customer_id or not name:
        return
    try:
        ts = now_iso()
        async with aiosqlite.connect(database.DB_PATH) as db:
            cur = await db.execute(
                "UPDATE customers SET name = ?, updated_at = ? WHERE id = ?",
                (name, ts, customer_id),
            )
            if cur.rowcount == 0:
                # Insert minimal row so the join in payments works next time.
                await db.execute(
                    "INSERT OR IGNORE INTO customers "
                    "(id, name, whatsapp, system_type, created_at, updated_at) "
                    "VALUES (?, ?, '', '', ?, ?)",
                    (customer_id, name, ts, ts),
                )
            await db.commit()
    except Exception:
        logger.exception("_persist_name failed for %s / %s", customer_id, name)
