# Read-only-ish check of payments_sync: SQLite counts, Mongo status counts, idempotent sync run
import asyncio, sqlite3, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from database import DB_PATH
from services.mongo_store import _get_db
from services.payments_sync import sync_payments


def local_counts():
    c = sqlite3.connect(DB_PATH)
    r = dict(c.execute("SELECT status, COUNT(*) FROM payments GROUP BY status").fetchall())
    c.close()
    return r


async def mongo_counts():
    db = _get_db()
    out = {}
    async for d in db.payments.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        out[d["_id"]] = d["n"]
    return out


async def main():
    print("DB_PATH", DB_PATH)
    print("local before", local_counts())
    print("mongo before", await mongo_counts())
    r1 = await sync_payments(); print("sync1", r1)
    print("local after1", local_counts())
    r2 = await sync_payments(); print("sync2", r2)
    print("local after2", local_counts())
    print("mongo after", await mongo_counts())

asyncio.run(main())
