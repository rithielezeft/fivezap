"""Command templates CRUD."""
from fastapi import APIRouter, HTTPException
from typing import List
import aiosqlite

from database import DB_PATH
from models import Template, TemplateCreate, TemplateUpdate, new_id, now_iso

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _row_to_template(row) -> Template:
    d = dict(row)
    d["requires_mac"] = bool(d["requires_mac"])
    d["enabled"] = bool(d["enabled"])
    d["trigger_source"] = d.get("trigger_source") or "both"
    return Template(**d)


@router.get("", response_model=List[Template])
async def list_templates():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM command_templates ORDER BY created_at DESC")
        return [_row_to_template(r) for r in await cur.fetchall()]


@router.post("", response_model=Template)
async def create_template(payload: TemplateCreate):
    tid = new_id()
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO command_templates (id, name, trigger_command, system_type, requires_mac, package_id, response_template, enabled, trigger_source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, payload.name, payload.trigger_command.strip(), payload.system_type,
                 int(payload.requires_mac), payload.package_id, payload.response_template,
                 int(payload.enabled), payload.trigger_source, now_iso()),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(409, "Trigger command already exists")
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM command_templates WHERE id = ?", (tid,))
        return _row_to_template(await cur.fetchone())


@router.put("/{template_id}", response_model=Template)
async def update_template(template_id: str, payload: TemplateUpdate):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "requires_mac" in fields:
        fields["requires_mac"] = int(fields["requires_mac"])
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    if not fields:
        raise HTTPException(400, "No fields to update")

    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [template_id]

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"UPDATE command_templates SET {sets} WHERE id = ?", values)
        if cur.rowcount == 0:
            raise HTTPException(404, "Template not found")
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM command_templates WHERE id = ?", (template_id,))
        return _row_to_template(await cur.fetchone())


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM command_templates WHERE id = ?", (template_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Template not found")
        await db.commit()
    return {"success": True}
