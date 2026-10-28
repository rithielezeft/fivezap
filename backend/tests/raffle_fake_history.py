# Helper: insert/remove a fake raffle_draws doc (_id=2000-01) for public replay UI testing. Usage: python raffle_fake_history.py add|del
import asyncio
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")


async def main(op):
    from services.mongo_store import _get_db
    db = _get_db()
    if op == "add":
        seq = [{"name": n, "coupon": f"{i % 5 + 1:05d}"} for i, n in enumerate(["joaonew", "mariaTEST", "Coringa 1", "pedroTEST", "anaTEST"] * 12)]
        seq[52] = {"name": "joaonew", "coupon": "00001"}
        await db.raffle_draws.replace_one({"_id": "2000-01"}, {"_id": "2000-01", "status": "drawn", "month": "2000-01",
                                          "winner": {"name": "joaonew", "coupon": "00001", "customer_id": "TEST"},
                                          "sequence": seq, "win_index": 52, "participants": 4, "total_clovers": 5,
                                          "prize_months": 1, "renewed": True}, upsert=True)
    else:
        await db.raffle_draws.delete_one({"_id": "2000-01"})
    print(op, "ok", await db.raffle_draws.count_documents({}))


asyncio.run(main(sys.argv[1]))
