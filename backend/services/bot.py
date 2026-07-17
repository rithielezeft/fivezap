"""Bot logic: process incoming WhatsApp messages, match templates, run actions."""
import json
import logging
import aiosqlite
from datetime import datetime, timezone

from database import DB_PATH
from models import new_id, now_iso
from services import painel, whatsapp_client

logger = logging.getLogger(__name__)


async def log_activity(activity_type: str, message: str, customer_id: str = None, status: str = "info", metadata: dict = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO activity_logs (id, type, customer_id, message, status, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id(), activity_type, customer_id, message, status,
             json.dumps(metadata) if metadata else None, now_iso()),
        )
        await db.commit()


async def save_message(phone: str, message: str, direction: str, customer_id: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (id, customer_id, phone, message, direction, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), customer_id, phone, message, direction, now_iso()),
        )
        await db.commit()


async def find_or_create_customer(phone: str, name: str = None) -> dict:
    """Find customer by whatsapp phone."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM customers WHERE whatsapp = ?", (phone,)
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        # Create a lightweight customer record
        cid = new_id()
        now = now_iso()
        await db.execute(
            "INSERT INTO customers (id, name, whatsapp, system_type, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, name or phone, phone, "unknown", "prospect", now, now),
        )
        await db.commit()
        return {"id": cid, "name": name or phone, "whatsapp": phone, "system_type": "unknown"}


def normalize_phone(phone: str) -> str:
    """Extract digits and strip whatsapp suffix."""
    return "".join(c for c in phone if c.isdigit())


async def process_incoming_message(phone: str, body: str, from_me: bool = False):
    """Handle a message from Node service."""
    phone_clean = normalize_phone(phone)
    direction = "out" if from_me else "in"
    customer = await find_or_create_customer(phone_clean)
    await save_message(phone_clean, body, direction, customer["id"])

    # Only process bot commands from client (incoming) or from admin (from_me)
    text = body.strip()
    if not text:
        return

    # Match template
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM command_templates WHERE enabled = 1"
        )
        templates = [dict(r) for r in await cur.fetchall()]

    matched = None
    for tpl in templates:
        # Respect trigger_source: client | admin | both
        source = (tpl.get("trigger_source") or "both").lower()
        if from_me and source == "client":
            continue
        if not from_me and source == "admin":
            continue
        trigger = tpl["trigger_command"].strip().lower()
        if text.lower().startswith(trigger):
            matched = tpl
            break

    if not matched:
        return

    # Extract MAC if needed
    remainder = text[len(matched["trigger_command"]):].strip()
    mac = None
    if matched["requires_mac"]:
        # Look for a mac-like pattern (12 hex chars with optional separators)
        import re
        m = re.search(r"([0-9A-Fa-f]{2}[:\-]?){5}[0-9A-Fa-f]{2}", remainder)
        if m:
            mac = m.group(0).upper()
        else:
            await whatsapp_client.send_message(
                phone_clean,
                f"⚠️ Para criar teste {matched['system_type'].upper()} preciso do seu MAC.\nEnvie: {matched['trigger_command']} AA:BB:CC:DD:EE:FF"
            )
            await save_message(phone_clean, "AWAITING_MAC", "out", customer["id"])
            return

    await log_activity("bot_trigger", f"Comando '{matched['trigger_command']}' de {phone_clean}", customer["id"], "info")

    try:
        # Call painel.fun to create trial
        result = await painel.create_trial(
            system_type=matched["system_type"],
            mac=mac,
            name=customer.get("name") or phone_clean,
            whatsapp=phone_clean,
        )

        # Store trial
        trial_id = new_id()
        painel_user = result.get("username") or result.get("user") or result.get("login")
        painel_pass = result.get("password") or result.get("pass")
        expires = result.get("expires_at") or result.get("expiration")
        trial_user_id = str(result.get("id") or result.get("user_id") or "")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO trials (id, customer_id, system_type, mac, painel_user, painel_pass, trial_user_id, expires_at, created_at, raw_response) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trial_id, customer["id"], matched["system_type"], mac,
                 painel_user, painel_pass, trial_user_id, expires, now_iso(),
                 json.dumps(result)),
            )
            # Update customer system_type + credentials
            await db.execute(
                "UPDATE customers SET system_type = ?, mac = COALESCE(?, mac), painel_username = ?, painel_password = ?, expires_at = ?, updated_at = ? WHERE id = ?",
                (matched["system_type"], mac, painel_user, painel_pass, expires, now_iso(), customer["id"])
            )
            await db.commit()

        # Compose response
        template = matched["response_template"] or (
            "✅ Teste {system_type} criado!\n👤 Usuário: {user}\n🔑 Senha: {pass}\n⏰ Expira em: {expires}"
        )
        from database import get_setting as _get_setting
        public_base = await _get_setting("public_base_url", "")
        pay_link = f"{public_base}/pay/{trial_user_id or painel_user or ''}" if public_base and (trial_user_id or painel_user) else ""

        response = (template
                    .replace("{system_type}", matched["system_type"].upper())
                    .replace("{user}", painel_user or "-")
                    .replace("{pass}", painel_pass or "-")
                    .replace("{expires}", expires or "24h")
                    .replace("{mac}", mac or "-")
                    .replace("{name}", customer.get("name") or "")
                    .replace("{pay_link}", pay_link))

        await whatsapp_client.send_message(phone_clean, response)
        await save_message(phone_clean, response, "out", customer["id"])
        await log_activity("trial_created", f"Teste {matched['system_type']} criado para {phone_clean}", customer["id"], "success", result)

        # Schedule 1h + 3h reminders
        try:
            from services.reminders import schedule as _schedule_reminder
            ctx = {
                "name": customer.get("name") or "",
                "user": painel_user or "",
                "pass": painel_pass or "",
                "expires": expires or "",
                "system_type": (matched["system_type"] or "").upper(),
                "mac": mac or "",
                "pay_link": pay_link,
            }
            await _schedule_reminder("trial_1h_reminder", phone_clean, 60 * 60, ctx)
            await _schedule_reminder("trial_expired", phone_clean, 3 * 60 * 60, ctx)
        except Exception:
            logger.exception("Failed to schedule trial reminders")

    except Exception as e:
        logger.exception("Failed to create trial: %s", e)
        await whatsapp_client.send_message(
            phone_clean,
            f"❌ Ocorreu um erro ao criar seu teste. Já avisamos o suporte."
        )
        await log_activity("trial_error", str(e), customer["id"], "error")
