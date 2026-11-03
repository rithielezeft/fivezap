# Helper: insert/remove temp paid payment with clovers for UI testing. Usage: python temp_clover_payment.py add|del
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
PID = "TEST_cloverui"


async def main(op):
    import aiosqlite
    from database import DB_PATH
    from services.mongo_store import _get_db
    async with aiosqlite.connect(DB_PATH) as db:
        if op == "add":
            now = datetime.now(timezone.utc).isoformat()
            await db.execute("INSERT OR REPLACE INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, created_at, paid_at, clovers) "
                             "VALUES (?,?,?,?,?,?,?,?,?)", (PID, "227470206", 1, 3400, 17, "paid", now, now, 3))
        else:
            await db.execute("DELETE FROM payments WHERE id LIKE 'TEST_%'")
        await db.commit()
        n = await (await db.execute("SELECT COUNT(*) FROM payments WHERE id LIKE 'TEST_%'")).fetchone()
    if op != "add":
        await _get_db().payments.delete_many({"id": {"$regex": "^TEST_"}})
    m = await _get_db().payments.count_documents({"id": {"$regex": "^TEST_"}})
    print(op, "sqlite TEST rows:", n[0], "mongo TEST rows:", m)


asyncio.run(main(sys.argv[1]))
