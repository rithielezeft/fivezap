"""Copy customers, trials, logs and painel users from SQLite to Supabase Postgres (one-way, periodic)."""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)
INTERVAL = 600
TABLES = {"customers": "whatsflow_customers", "trials": "whatsflow_trials", "activity_logs": "whatsflow_logs"}
PAINEL_TABLE = "whatsflow_painel_users"
state = {"last_run": None, "last_error": None, "counts": {}}


def configured() -> bool:
    return bool(os.environ.get("SUPABASE_DB_URL"))


async def _connect():
    import asyncpg
    from urllib.parse import unquote
    raw = os.environ["SUPABASE_DB_URL"].strip()
    rest = raw.split("://", 1)[1]
    userinfo, hostpart = rest.rsplit("@", 1)  # password may contain @ : / # unencoded
    user, password = userinfo.split(":", 1)
    hostport, _, db = hostpart.split("?", 1)[0].partition("/")
    host, _, port = hostport.partition(":")
    return await asyncpg.connect(host=host, port=int(port or 5432), user=unquote(user), password=unquote(password),
                                 database=db or "postgres", ssl="require", statement_cache_size=0, timeout=20)


async def _ensure(conn):
    for t in [*TABLES.values(), PAINEL_TABLE]:
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS public.{t} (id text PRIMARY KEY, data jsonb NOT NULL, "
            "created_at timestamptz, synced_at timestamptz NOT NULL DEFAULT now())")
        await conn.execute(f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY")


def _ts(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _upsert(conn, table: str, rows: list) -> int:
    if not rows:
        return 0
    await conn.executemany(
        f"INSERT INTO public.{table} (id, data, created_at) VALUES ($1, $2::jsonb, $3) "
        f"ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, synced_at = now() "
        f"WHERE public.{table}.data IS DISTINCT FROM EXCLUDED.data",
        [(str(r["id"]), json.dumps(r, default=str), _ts(r.get("created_at"))) for r in rows])
    return len(rows)


async def _with_atlas(collection: str, local: list) -> list:
    """Atlas keeps customers/trials from every install; local SQLite rows win on the same id."""
    from services.mongo_store import _get_db
    by_id = {}
    try:
        async for d in _get_db()[collection].find({}):
            d["id"] = str(d.pop("_id"))
            by_id[d["id"]] = d
    except Exception as e:
        logger.warning("atlas %s read failed: %s", collection, e)
    for r in local:
        by_id[str(r["id"])] = r
    return list(by_id.values())


async def sync_once() -> dict:
    conn = await _connect()
    try:
        await _ensure(conn)
        counts = {}
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            for src, dst in TABLES.items():
                where, params = "", ()
                if src == "activity_logs":
                    last = await conn.fetchval(f"SELECT max(created_at) FROM public.{dst}")
                    if last:
                        where, params = " WHERE created_at > ?", (last.astimezone(timezone.utc).isoformat(),)
                rows = [dict(r) for r in await (await db.execute(f"SELECT * FROM {src}{where}", params)).fetchall()]
                if src in ("customers", "trials"):
                    rows = await _with_atlas(src, rows)
                counts[src] = await _upsert(conn, dst, rows)
        from routers.painel_users import _read_cache
        users, _ = await _read_cache()
        counts["painel_users"] = await _upsert(conn, PAINEL_TABLE, [u for u in users or [] if u.get("id") is not None])
        state.update(last_run=datetime.now(timezone.utc).isoformat(), last_error=None, counts=counts)
        return counts
    finally:
        await conn.close()


async def mirror_loop():
    await asyncio.sleep(30)
    while True:
        if configured():
            try:
                counts = await sync_once()
                logger.info("supabase mirror synced: %s", counts)
            except Exception as e:
                state.update(last_run=datetime.now(timezone.utc).isoformat(), last_error=str(e)[:300])
                logger.warning("supabase mirror failed: %s", e)
        await asyncio.sleep(INTERVAL)
