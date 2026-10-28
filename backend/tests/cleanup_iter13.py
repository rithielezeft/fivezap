# Cleanup helper for iter13: removes TEST_ payments (SQLite+Mongo), raffle_display_names setting, resets joker_count
import asyncio
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")


async def main():
    import aiosqlite
    from database import DB_PATH, set_setting
    from services.mongo_store import _get_db
    mdb = _get_db()
    await set_setting("raffle_joker_count", "0")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM payments WHERE id LIKE 'TEST_%'")
        await db.execute("DELETE FROM settings WHERE key='raffle_display_names'")
        await db.commit()
        p = await (await db.execute("SELECT COUNT(*) FROM payments WHERE id LIKE 'TEST_%'")).fetchone()
        s = await (await db.execute("SELECT key, value FROM settings WHERE key LIKE 'raffle%'")).fetchall()
    await mdb.payments.delete_many({"$or": [{"_id": {"$regex": "^TEST"}}, {"id": {"$regex": "^TEST"}}]})
    await mdb.settings.delete_many({"$or": [{"_id": "raffle_display_names"}, {"key": "raffle_display_names"}]})
    print("sqlite TEST payments:", p[0], "settings:", s)
    print("mongo TEST payments:", await mdb.payments.count_documents({"$or": [{"_id": {"$regex": "^TEST"}}, {"id": {"$regex": "^TEST"}}]}))
    print("mongo display_names:", await mdb.settings.count_documents({"$or": [{"_id": "raffle_display_names"}, {"key": "raffle_display_names"}]}))
    print("mongo joker_count:", await mdb.settings.find_one({"_id": "raffle_joker_count"}))
    print("raffle_draws:", await mdb.raffle_draws.count_documents({}))


asyncio.run(main())
