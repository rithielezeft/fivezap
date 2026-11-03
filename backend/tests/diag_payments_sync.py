# Diagnose Mongo docs not present locally + time a sync run
import asyncio, sqlite3, sys, time
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from database import DB_PATH
from services.mongo_store import _get_db
from services.payments_sync import sync_payments


async def main():
    c = sqlite3.connect(DB_PATH)
    ids = {r[0] for r in c.execute("SELECT id FROM payments")}
    print("local renewed:", c.execute("SELECT COUNT(*) FROM payments WHERE status='renewed'").fetchone())
    c.close()
    db = _get_db()
    async for d in db.payments.find({}):
        if str(d["_id"]) not in ids:
            print("MISSING", d["_id"], d.get("status"), d.get("created_at"), d.get("paid_at"),
                  {k: d.get(k) for k in ("customer_id", "plan_months", "amount_cents", "package_id")})
    t = time.time()
    print("sync2", await sync_payments(), "took %.1fs" % (time.time() - t))
    c = sqlite3.connect(DB_PATH)
    print("local after2", dict(c.execute("SELECT status, COUNT(*) FROM payments GROUP BY status").fetchall()))
    agg = {}
    async for d in db.payments.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        agg[d["_id"]] = d["n"]
    print("mongo after", agg)

asyncio.run(main())
