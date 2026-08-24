"""Customer CRUD endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import aiosqlite
from typing import List, Optional

from database import DB_PATH
from models import Customer, CustomerCreate, CustomerUpdate, new_id, now_iso

router = APIRouter(prefix="/api/customers", tags=["customers"])


class SetWhatsappPayload(BaseModel):
    painel_username: str
    whatsapp: str
    name: Optional[str] = None


@router.post("/set-whatsapp-by-painel")
async def set_whatsapp_by_painel(payload: SetWhatsappPayload):
    """Upsert a customer by painel_username and set/lock its whatsapp.

    Used by the frontend Customers page (which shows painel users, not
    internal customer records) to edit the phone number manually. Always
    sets `whatsapp_locked=1` so future painel refreshes don't overwrite.
    """
    if not payload.painel_username or not payload.whatsapp:
        raise HTTPException(400, "painel_username e whatsapp são obrigatórios")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM customers WHERE painel_username = ? LIMIT 1",
            (payload.painel_username,),
        )
        existing = await cur.fetchone()

        if existing:
            await db.execute(
                "UPDATE customers SET whatsapp = ?, whatsapp_locked = 1, "
                "updated_at = ? WHERE id = ?",
                (payload.whatsapp, now_iso(), existing["id"]),
            )
            cid = existing["id"]
        else:
            cid = new_id()
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, whatsapp_locked, "
                "system_type, painel_username, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, 'iptv', ?, 'active', ?, ?)",
                (cid, payload.name or payload.painel_username, payload.whatsapp,
                 payload.painel_username, now_iso(), now_iso()),
            )
        await db.commit()
    return {"success": True, "customer_id": cid, "whatsapp_locked": True}


@router.get("", response_model=List[Customer])
async def list_customers(status: str = None, system_type: str = None):
    query = "SELECT * FROM customers WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if system_type:
        query += " AND system_type = ?"
        params.append(system_type)
    query += " ORDER BY created_at DESC"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, params)
        rows = await cur.fetchall()
        return [Customer(**dict(r)) for r in rows]


@router.get("/{customer_id}", response_model=Customer)
async def get_customer(customer_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Customer not found")
        return Customer(**dict(row))


@router.post("", response_model=Customer)
async def create_customer(payload: CustomerCreate):
    cid = new_id()
    now = now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO customers (id, name, whatsapp, system_type, mac, painel_username, painel_password, notes, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (cid, payload.name, payload.whatsapp, payload.system_type, payload.mac,
             payload.painel_username, payload.painel_password, payload.notes, now, now),
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM customers WHERE id = ?", (cid,))
        return Customer(**dict(await cur.fetchone()))


@router.put("/{customer_id}", response_model=Customer)
async def update_customer(customer_id: str, payload: CustomerUpdate):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    # If admin manually edited the whatsapp, LOCK it so painel refreshes
    # don't overwrite it. `whatsapp_locked=1` signals "manual override —
    # keep this even if painel returns a different number".
    if "whatsapp" in fields:
        fields["whatsapp_locked"] = 1
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [customer_id]

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"UPDATE customers SET {sets} WHERE id = ?", values)
        if cur.rowcount == 0:
            raise HTTPException(404, "Customer not found")
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
        return Customer(**dict(await cur.fetchone()))


@router.delete("/{customer_id}")
async def delete_customer(customer_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Customer not found")
        await db.commit()
    return {"success": True}
