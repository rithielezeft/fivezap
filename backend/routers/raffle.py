"""Admin + public endpoints for the Trevo da Sorte raffle."""
from fastapi import APIRouter, HTTPException, Request

from database import set_setting
from services import raffle

router = APIRouter(tags=["raffle"])


@router.get("/api/raffle")
async def raffle_overview():
    cfg = await raffle.config()
    cur = await raffle.entries()
    by_customer = {}
    for p in cur["pool"]:
        k = p["customer_id"]
        by_customer.setdefault(k, {"customer_id": k, "name": p["name"], "joker": bool(p.get("joker")), "coupons": []})["coupons"].append(p["coupon"])
    return {"config": cfg, "month": cur["month"], "draw_at": cur["draw_at"], "participants": cur["participants"],
            "clovers": cur["clovers"], "entries": list(by_customer.values()), "history": await raffle.history()}


@router.put("/api/raffle/settings")
async def raffle_settings(request: Request):
    body = await request.json()
    for k, v in raffle.clean_settings_payload(body).items():
        await set_setting(k, v)
    return await raffle.config()


@router.post("/api/raffle/draw")
async def raffle_draw_now():
    try:
        return await raffle.perform_draw()
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/public/raffle")
async def raffle_public():
    cfg = await raffle.config()
    cur = await raffle.entries()
    last = (await raffle.history(1) or [None])[0]
    return {"enabled": cfg["enabled"], "clover_cents": cfg["clover_cents"], "prize_months": cfg["prize_months"],
            "max_clovers": cfg["max_clovers"], "participants": cur["participants"], "draw_at": cur["draw_at"],
            "last_winner": {"month": last["month"], "name": last["winner"]["name"]} if last else None}
