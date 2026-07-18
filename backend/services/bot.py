"""Bot logic: process incoming WhatsApp messages, match templates, run actions."""
import json
import logging
import re
import aiosqlite
from datetime import datetime, timezone
from typing import Optional

from database import DB_PATH
from models import new_id, now_iso
from services import painel, whatsapp_client

logger = logging.getLogger(__name__)

# In-memory dedup cache: key -> timestamp
_recent_messages: dict = {}

# Pending MAC state: phone -> {template_id, attempts, started_at, name}
_pending_mac: dict = {}
_MAX_MAC_ATTEMPTS = 3
_MAC_STATE_TTL = 15 * 60  # 15 minutes

# MAC regex — TWO patterns to avoid confusing with phone numbers:
# 1) Separated form: AA:BB:CC:DD:EE:FF or AA-BB-CC-DD-EE-FF  (definitive)
# 2) Plain 12-char hex ONLY if it contains at least one letter a-f (so phone
#    numbers like 5511987654321 are rejected)
_MAC_SEP_RE = re.compile(
    r"([0-9A-Fa-f]{2})[:\-]([0-9A-Fa-f]{2})[:\-]([0-9A-Fa-f]{2})[:\-]"
    r"([0-9A-Fa-f]{2})[:\-]([0-9A-Fa-f]{2})[:\-]([0-9A-Fa-f]{2})"
)
_MAC_PLAIN_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{12})(?![0-9A-Fa-f])")


def _parse_mac(text: str) -> Optional[str]:
    """Extract and normalize MAC from arbitrary text.

    Accepts formats:
      - AA:BB:CC:DD:EE:FF  (always)
      - AA-BB-CC-DD-EE-FF  (always)
      - AABBCCDDEEFF       (only if contains a hex letter — to avoid matching
                            phone numbers like 5511987654321)
    Returns normalized uppercase AA:BB:CC:DD:EE:FF or None.
    """
    if not text:
        return None
    m = _MAC_SEP_RE.search(text)
    if m:
        return ":".join(g.upper() for g in m.groups())
    m = _MAC_PLAIN_RE.search(text)
    if m:
        hexstr = m.group(1)
        if any(c.lower() in "abcdef" for c in hexstr):
            return ":".join(hexstr[i:i + 2].upper() for i in range(0, 12, 2))
    return None


_MAC_FORMAT_HELP = (
    "❌ Não consegui identificar seu MAC.\n\n"
    "📱 Como enviar corretamente:\n"
    "• 6 pares hexadecimais separados por dois-pontos\n"
    "• Exemplo: `AA:BB:CC:DD:EE:FF`\n"
    "• Também aceito: `AA-BB-CC-DD-EE-FF` ou `AABBCCDDEEFF`\n\n"
    "💡 Onde encontrar o MAC no seu MAG/Formuler:\n"
    "Menu → Configurações → Info do sistema → Endereço MAC"
)


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
    """Find customer by whatsapp phone. If found and name is provided, update
    the customer's display name (upgrading from JID/phone to real WhatsApp name)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM customers WHERE whatsapp = ?", (phone,)
        )
        row = await cur.fetchone()
        if row:
            existing = dict(row)
            # Upgrade name if the current one is just the phone/JID and we have a real one
            if name and existing.get("name") in (None, "", phone) and name != phone:
                await db.execute(
                    "UPDATE customers SET name = ?, updated_at = ? WHERE id = ?",
                    (name, now_iso(), existing["id"]),
                )
                await db.commit()
                existing["name"] = name
            return existing
        # Create a lightweight customer record
        cid = new_id()
        now = now_iso()
        display_name = name or phone
        await db.execute(
            "INSERT INTO customers (id, name, whatsapp, system_type, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, display_name, phone, "unknown", "prospect", now, now),
        )
        await db.commit()
        return {"id": cid, "name": display_name, "whatsapp": phone, "system_type": "unknown"}


def normalize_phone(phone: str) -> str:
    """Normalize phone/JID.

    We preserve @lid suffix because WhatsApp's new privacy protocol uses LID
    identifiers where the real phone number is hidden. For sending back we need
    to use the exact same JID (not the digits alone).

    Returns:
      - '123@lid' → '123@lid' (kept intact — used as chat target)
      - '5511987654321@c.us' → '5511987654321' (drop suffix, plain phone)
      - '5511987654321' → '5511987654321' (already plain)
    """
    if not phone:
        return ""
    s = str(phone).strip()
    if s.endswith("@lid"):
        return s
    if "@" in s:
        return s.split("@")[0]
    return "".join(c for c in s if c.isdigit())


async def process_incoming_message(
    phone: str,
    body: str,
    from_me: bool = False,
    name: Optional[str] = None,
):
    """Handle a message from Node service."""
    phone_clean = normalize_phone(phone)

    # Backend-side dedup: if the exact same phone+body+direction was processed
    # in the last 30 seconds, skip. Prevents the bot from creating a trial twice
    # if the Node service somehow fires message_create more than once.
    dedup_key = f"{phone_clean}|{'out' if from_me else 'in'}|{body[:80]}"
    now_ts = datetime.now(timezone.utc).timestamp()
    global _recent_messages  # noqa: PLW0602
    _recent_messages = {k: t for k, t in _recent_messages.items() if now_ts - t < 30}
    if dedup_key in _recent_messages:
        logger.info("Duplicate incoming message suppressed: %s", dedup_key[:80])
        return
    _recent_messages[dedup_key] = now_ts

    direction = "out" if from_me else "in"
    customer = await find_or_create_customer(phone_clean, name)
    await save_message(phone_clean, body, direction, customer["id"])

    text = (body or "").strip()
    logger.info(
        "process_incoming: phone=%s from_me=%s text=%r customer=%s",
        phone_clean, from_me, text[:80], customer["id"],
    )

    if not text:
        return

    # ---------- Pending MAC follow-up ----------
    # If we're waiting for a MAC from this phone (previous trigger asked for it),
    # try to parse it here BEFORE running the template match. Client-side only
    # (admin messages don't trigger MAC state).
    if not from_me and phone_clean in _pending_mac:
        state = _pending_mac[phone_clean]
        if now_ts - state["started_at"] > _MAC_STATE_TTL:
            _pending_mac.pop(phone_clean, None)
            logger.info("MAC state expired for %s", phone_clean)
        else:
            mac_candidate = _parse_mac(text)
            if mac_candidate:
                logger.info("MAC received from %s (attempt %s): %s", phone_clean, state["attempts"] + 1, mac_candidate)
                # Load the template and fire the trial with this MAC
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    cur = await db.execute(
                        "SELECT * FROM command_templates WHERE id = ? AND enabled = 1",
                        (state["template_id"],),
                    )
                    row = await cur.fetchone()
                if not row:
                    _pending_mac.pop(phone_clean, None)
                    logger.warning("Pending MAC template %s no longer exists", state["template_id"])
                    return
                tpl = dict(row)
                _pending_mac.pop(phone_clean, None)
                await _run_trial_creation(customer, tpl, mac_candidate, phone_clean)
                return
            # Not a MAC — count as a failed attempt
            state["attempts"] += 1
            remaining = _MAX_MAC_ATTEMPTS - state["attempts"]
            if state["attempts"] >= _MAX_MAC_ATTEMPTS:
                _pending_mac.pop(phone_clean, None)
                await whatsapp_client.send_message(
                    phone_clean,
                    "🙈 Não consegui identificar o MAC após 3 tentativas.\n\n"
                    "Envie novamente o comando junto com o MAC no formato correto (`AA:BB:CC:DD:EE:FF`) "
                    "ou fale com um atendente pelo botão de suporte. 💛"
                )
                await save_message(phone_clean, "MAC_ATTEMPTS_EXHAUSTED", "out", customer["id"])
                await log_activity(
                    "bot_mac_exhausted",
                    f"Cliente {phone_clean} esgotou 3 tentativas de MAC",
                    customer["id"], "warning",
                )
                return
            await whatsapp_client.send_message(
                phone_clean,
                f"{_MAC_FORMAT_HELP}\n\n"
                f"Você ainda tem *{remaining}* {'tentativa' if remaining == 1 else 'tentativas'}."
            )
            await save_message(phone_clean, "MAC_INVALID", "out", customer["id"])
            return

    # Match template
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM command_templates WHERE enabled = 1"
        )
        templates = [dict(r) for r in await cur.fetchall()]

    logger.info("Loaded %d enabled command_templates", len(templates))

    if not templates:
        # Loud alert: no templates = bot won't respond to anyone
        logger.warning(
            "⚠️  NENHUM template ativo em command_templates. Configure em /templates "
            "no painel WhatsFlow ou o bot NUNCA vai responder."
        )
        await log_activity(
            "bot_no_templates",
            f"Mensagem recebida mas nenhum template ativo. Texto: {text[:100]}",
            customer["id"], "warning",
        )
        return

    matched = None
    for tpl in templates:
        source = (tpl.get("trigger_source") or "both").lower()
        if from_me and source == "client":
            continue
        if not from_me and source == "admin":
            continue
        trigger = tpl["trigger_command"].strip().lower()
        if text.lower().startswith(trigger):
            matched = tpl
            logger.info("Matched template '%s' (trigger=%r)", tpl["name"], trigger)
            break

    if not matched:
        available = ", ".join(t["trigger_command"] for t in templates)
        logger.info(
            "No template matched. Text=%r (available triggers: %s)",
            text[:80], available,
        )
        await log_activity(
            "bot_no_match",
            f"'{text[:60]}' não bateu com nenhum template. Disponíveis: {available}",
            customer["id"], "info",
        )
        return

    # Extract MAC if needed
    remainder = text[len(matched["trigger_command"]):].strip()
    mac = None
    if matched["requires_mac"]:
        mac = _parse_mac(remainder)
        if not mac:
            logger.info("Requires MAC but none in message — asking client (attempts=0)")
            _pending_mac[phone_clean] = {
                "template_id": matched["id"],
                "attempts": 0,
                "started_at": now_ts,
                "customer_id": customer["id"],
            }
            await whatsapp_client.send_message(
                phone_clean,
                f"📺 Para criar seu teste {matched['system_type'].upper()} preciso do endereço MAC do seu aparelho.\n\n"
                f"📱 Formato: `AA:BB:CC:DD:EE:FF`\n"
                f"💡 Onde encontrar: Menu → Configurações → Info do sistema → Endereço MAC\n\n"
                f"Você tem {_MAX_MAC_ATTEMPTS} tentativas para enviar o MAC correto."
            )
            await save_message(phone_clean, "AWAITING_MAC", "out", customer["id"])
            return

    await _run_trial_creation(customer, matched, mac, phone_clean)


async def _run_trial_creation(customer: dict, matched: dict, mac: Optional[str], phone_clean: str):
    """Actually invoke painel.create_trial, persist result, send response to client.

    Extracted from process_incoming_message so the MAC-retry flow can call it
    once a valid MAC arrives on a subsequent message.
    """
    await log_activity("bot_trigger", f"Comando '{matched['trigger_command']}' de {phone_clean}", customer["id"], "info")
    logger.info(
        "Creating trial via painel.fun: system=%s mac=%s customer=%s",
        matched["system_type"], mac, customer["id"],
    )

    try:
        # Call painel.fun to create trial
        result = await painel.create_trial(
            system_type=matched["system_type"],
            mac=mac,
            name=customer.get("name") or phone_clean,
            # For LID chats we can't send a real phone to painel.fun — send only if plain
            whatsapp=phone_clean if not phone_clean.endswith("@lid") else "",
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
            "✅ Teste {system_type} criado!\n👤 Usuário: {user}\n🔑 Senha: {pass}\n⏰ Expira em: {expires}\n\n💳 Já quer garantir sua assinatura? {pay_link}"
        )
        from database import get_setting as _get_setting

        public_base = await _get_setting("public_base_url", "")
        pay_links_by_plan: dict = {}

        # {pay_link} is ALWAYS the short local URL /pay/{painel_id}. The /pay
        # page hosts all plan options — cleaner to share on WhatsApp than a
        # 300-char InfinitePay URL.
        payment_ref_id = trial_user_id or painel_user or customer["id"]
        checkout_link = f"{public_base}/pay/{payment_ref_id}" if public_base else ""

        # Per-plan InfinitePay direct links ({pay_link_1m}, _3m, _6m, _12m)
        # remain long InfinitePay URLs so the admin can send a one-click
        # checkout for a specific plan.
        if trial_user_id or painel_user:
            for months in (1, 3, 6, 12):
                try:
                    price_raw = await _get_setting(f"plan_price_{months}m", "35,00")
                    amount_cents = int(round(float(str(price_raw).replace(",", ".").strip()) * 100))
                    if amount_cents <= 0:
                        continue
                    from services import infinitepay
                    # Use the painel trial id as order reference — the
                    # InfinitePay webhook can renew the exact user that
                    # took the test.
                    order_ref = trial_user_id or painel_user or trial_id[:12]
                    result_link = await infinitepay.create_payment_link(
                        order_nsu=f"trial-{order_ref}-{months}m",
                        amount_cents=amount_cents,
                        description=f"Assinatura {matched['system_type'].upper()} — {months} {'mês' if months == 1 else 'meses'}",
                        redirect_url=f"{public_base}/pay/{payment_ref_id}?ok=1" if public_base else None,
                        webhook_url=f"{public_base}/api/payments/webhook" if public_base else None,
                        customer_name=customer.get("name"),
                        customer_phone=phone_clean if not phone_clean.endswith("@lid") else None,
                    )
                    pay_links_by_plan[months] = result_link["url"]
                except Exception as pay_err:
                    logger.warning("Failed to generate InfinitePay link for %dm: %s", months, pay_err)

        response = (template
                    .replace("{system_type}", matched["system_type"].upper())
                    .replace("{user}", painel_user or "-")
                    .replace("{pass}", painel_pass or "-")
                    .replace("{expires}", expires or "24h")
                    .replace("{mac}", mac or "-")
                    .replace("{name}", customer.get("name") or "")
                    .replace("{pay_link}", checkout_link or "")
                    .replace("{pay_link_1m}", pay_links_by_plan.get(1, checkout_link) or "")
                    .replace("{pay_link_3m}", pay_links_by_plan.get(3, "") or "")
                    .replace("{pay_link_6m}", pay_links_by_plan.get(6, "") or "")
                    .replace("{pay_link_12m}", pay_links_by_plan.get(12, "") or ""))

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
                "pay_link": checkout_link,
                "pay_link_1m": pay_links_by_plan.get(1, checkout_link) or "",
                "pay_link_3m": pay_links_by_plan.get(3, "") or "",
                "pay_link_6m": pay_links_by_plan.get(6, "") or "",
                "pay_link_12m": pay_links_by_plan.get(12, "") or "",
            }
            await _schedule_reminder("trial_1h_reminder", phone_clean, 60 * 60, ctx)
            await _schedule_reminder("trial_expired", phone_clean, 3 * 60 * 60, ctx)
        except Exception:
            logger.exception("Failed to schedule trial reminders")

        # Fire-and-forget: refresh the painel users cache so the /customers
        # page in the admin panel shows the newly-created trial immediately.
        try:
            import asyncio as _asyncio
            from routers.painel_users import refresh_cache_task
            _asyncio.create_task(refresh_cache_task())
            logger.info("Scheduled painel users cache refresh after trial creation")
        except Exception:
            logger.exception("Failed to schedule painel users cache refresh")

    except Exception as e:
        logger.exception("Failed to create trial: %s", e)
        # Show detailed error to help debugging — the client will see the actual reason
        err_short = str(e)[:200] if str(e) else "erro desconhecido"
        await whatsapp_client.send_message(
            phone_clean,
            f"❌ Não conseguimos criar seu teste agora.\n\n"
            f"Motivo: {err_short}\n\n"
            f"Já avisamos o suporte, tente novamente em alguns minutos."
        )
        await log_activity("trial_error", str(e)[:500], customer["id"], "error")
