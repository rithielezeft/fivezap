
"""Admin + public endpoints for the Trevo da Sorte raffle."""

import hashlib

from fastapi import APIRouter, HTTPException, Request

from database import set_setting
from services import raffle

router = APIRouter(tags=["raffle"])


NOMES_COMUNS = [
    "João", "Maria", "Pedro", "Ana", "Lucas",
    "Júlia", "Gabriel", "Beatriz", "Matheus", "Laura",
    "Felipe", "Mariana", "Rafael", "Camila", "Gustavo",
    "Amanda", "Bruno", "Larissa", "Thiago", "Letícia",
    "Daniel", "Isabela", "André", "Carolina", "Leonardo",
    "Fernanda", "Marcelo", "Patrícia", "Eduardo", "Juliana",
    "Rodrigo", "Aline", "Vinícius", "Bianca", "Diego",
    "Renata", "Ricardo", "Sofia", "Henrique", "Gabriela",
    "Alex", "Cristina", "Samuel", "Vitória", "Caio",
    "Luana", "Igor", "Nicole", "Antônio", "Clara",
    "José", "Helena", "Luiz", "Isadora", "Miguel",
    "Alice", "Arthur", "Manuela", "Davi", "Lívia"
]


def joker_display_name(coupon):
    """Returns a stable common name for a joker coupon."""
    value = str(coupon)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(NOMES_COMUNS)
    return NOMES_COMUNS[index]


def display_name(participant, mask_name):
    """Returns the appropriate public display name."""
    if participant.get("joker"):
        return joker_display_name(participant["coupon"])

    return mask_name(participant["name"])


@router.get("/api/raffle")
async def raffle_overview():
    cfg = await raffle.config()
    cur = await raffle.entries()

    by_customer = {}

    for p in cur["pool"]:
        k = p["coupon"] if p.get("joker") else p["customer_id"]

        by_customer.setdefault(
            k,
            {
                "customer_id": k,
                "name": p["name"],
                "joker": bool(p.get("joker")),
                "coupons": []
            }
        )["coupons"].append(p["coupon"])

    return {
        "config": cfg,
        "month": cur["month"],
        "draw_at": cur["draw_at"],
        "participants": cur["participants"],
        "clovers": cur["clovers"],
        "entries": list(by_customer.values()),
        "history": await raffle.history()
    }


@router.put("/api/raffle/settings")
async def raffle_settings(request: Request):
    body = await request.json()

    for k, v in raffle.clean_settings_payload(body).items():
        await set_setting(k, v)

    return await raffle.config()


@router.put("/api/raffle/participant-name")
async def raffle_participant_name(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    if not isinstance(body, dict):
        raise HTTPException(400, "Corpo inválido")

    cid = str(body.get("customer_id") or "").strip()
    new_name = str(body.get("name") or "").strip()

    if not new_name:
        raise HTTPException(400, "Informe um nome válido")

    if new_name.lower().startswith("coringa"):
        raise HTTPException(
            400,
            "Esse nome é reservado para os coringas"
        )

    cur = await raffle.entries()

    real = {
        p["customer_id"]
        for p in cur["pool"]
        if not p.get("joker")
    }

    if cid not in real:
        raise HTTPException(
            400,
            "Só é possível renomear participantes que compraram trevo"
        )

    await raffle.set_display_name(cid, new_name)

    return {"ok": True}


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
    hist = await raffle.history(12)

    last = hist[0] if hist else None
    mask_name = raffle.mask_name

    return {
        "enabled": cfg["enabled"],
        "clover_cents": cfg["clover_cents"],
        "prize_months": cfg["prize_months"],
        "max_clovers": cfg["max_clovers"],
        "participants": cur["participants"],
        "draw_at": cur["draw_at"],
        "month": cur["month"],
        "clovers": cur["clovers"],

        "entries": [
            {
                "name": display_name(p, mask_name),
                "coupon": p["coupon"],
                "joker": bool(p.get("joker"))
            }
            for p in cur["pool"]
        ],

        "last_winner": {
            "month": last["month"],
            "name": mask_name(last["winner"]["name"])
        } if last else None,

        "history": [
            {
                "month": h["month"],
                "participants": h.get("participants"),
                "total_clovers": h.get("total_clovers"),
                "prize_months": h.get("prize_months"),
                "win_index": h.get("win_index"),

                "winner": {
                    "name": mask_name(h["winner"]["name"]),
                    "coupon": h["winner"]["coupon"]
                },

                "sequence": [
                    {
                        "name": mask_name(x["name"]),
                        "coupon": x["coupon"]
                    }
                    for x in h.get("sequence", [])
                ]
            }
            for h in hist
        ]
    }
