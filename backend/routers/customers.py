"""Customer CRUD endpoints."""
from fastapi import APIRouter, HTTPException
import aiosqlite
from typing import List

from database import DB_PATH
from models import Customer, CustomerCreate, CustomerUpdate, new_id, now_iso

router = APIRouter(prefix="/api/customers", tags=["customers"])


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
