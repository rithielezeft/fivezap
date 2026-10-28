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


def _mac_where_to_find(system_type: Optional[str]) -> str:
    """Return device-specific instructions on where to locate the MAC address.

    DreamTV (IPTV flow): MAC shown in the CORNER of the DreamTV app screen.
    Hybrid (MAG/Formuler boxes): MAC in the Settings menu.
    """
    if (system_type or "").lower() == "iptv":
        return (
            "💡 Onde encontrar o MAC no DreamTV:\n"
            "Abra o app *DreamTV* no seu dispositivo — o endereço MAC aparece "
            "no *canto da tela* assim que o app carrega."
        )
    # Hybrid / MAG / Formuler
    return (
        "💡 Onde encontrar o MAC no seu MAG/Formuler:\n"
        "Menu → Configurações → Info do sistema → Endereço MAC"
    )


def _mac_format_help(system_type: Optional[str]) -> str:
    return (
        "❌ Não consegui identificar seu MAC.\n\n"
        "📱 Como enviar corretamente:\n"
        "• 6 pares hexadecimais separados por dois-pontos\n"
        "• Exemplo: `AA:BB:CC:DD:EE:FF`\n"
        "• Também aceito: `AA-BB-CC-DD-EE-FF` ou `AABBCCDDEEFF`\n\n"
        f"{_mac_where_to_find(system_type)}"
    )


def _infer_system_type(trigger: str, name: str, current: str) -> str:
    """Guard against mis-configured templates.

    Some production templates had `system_type='iptv'` but the trigger/name
    clearly said "hybrid" or "dream tv" — which caused the wrong flow to run
    (Hybrid ending up as DreamTV IPTV, and DreamTV ending up as plain IPTV).
    We infer from trigger+name and override when they contradict.

    Priority: hybrid > p2p > iptv (DreamTV) > iptv (plain).
    """
    text = f"{trigger} {name}".lower()
    if any(k in text for k in ("hybrid", "híbrido", "hibrido")):
        return "hybrid"
    if "p2p" in text or "p2 p" in text or "braz" in text:
        return "p2p"
    # "dream tv", "dreamtv" → still IPTV type but with MAC (DreamTV flow)
    if "dream" in text or "dreamtv" in text:
        return "iptv"
    if current in ("iptv", "p2p", "hybrid"):
        return current
    return "iptv"


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
    from services.phone_extractor import br_variants
    variants = br_variants(phone) if phone and not str(phone).endswith("@lid") else [phone]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"SELECT * FROM customers WHERE whatsapp IN ({','.join('?' * len(variants))}) ORDER BY whatsapp = ? DESC",
            (*variants, phone),
        )
        row = await cur.fetchone()
        if row and row["whatsapp"] != phone and not row["whatsapp"].endswith("@lid"):
            # Legacy row saved without the 9th digit → upgrade to canonical form.
            await db.execute("UPDATE customers SET whatsapp = ? WHERE id = ? AND (whatsapp_locked IS NULL OR whatsapp_locked = 0)",
                             (phone, row["id"]))
            await db.commit()
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


async def _update_customer_name(customer_id: str, name: str):
    """Persist a real client name (typed by them or extracted from message).
    Only updates when we actually got a proper name — never overwrite with
    empty/placeholder values."""
    if not customer_id or not name or not name.strip():
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE customers SET name = ?, updated_at = ? WHERE id = ?",
            (name.strip(), now_iso(), customer_id),
        )
        await db.commit()


# Client name extraction — many clients introduce themselves before/with the
# trial command. Parse common Portuguese patterns so we don't have to ask.
_NAME_PATTERNS = [
    # "meu nome é João", "meu nome eh Ana", "nome: Pedro"
    re.compile(r"(?:meu\s+nome\s+(?:é|eh|e)|nome[:\s]+)\s*([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})", re.IGNORECASE),
    # "sou o Pedro", "sou a Maria", "eu sou Pedro", "aqui é o João"
    re.compile(r"(?:sou\s+(?:o|a)?|eu\s+sou|aqui\s+(?:é|eh|e)\s+(?:o|a)?)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})", re.IGNORECASE),
    # "chamo-me Pedro" / "me chamo Pedro"
    re.compile(r"(?:me\s+chamo|chamo-me)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+){0,2})", re.IGNORECASE),
    # "boa tarde, Pedro aqui" — pattern needs the word "aqui" after
    re.compile(r"[,\.]\s*([A-Za-zÀ-ÿ]{3,15})\s+aqui\b", re.IGNORECASE),
]

# Words that are NOT names (avoid false positives from greetings/etc.)
_NOT_A_NAME = {
    "amigo", "amiga", "cara", "brother", "mano", "cliente", "pessoal",
    "bom dia", "boa tarde", "boa noite", "oi", "ola", "olá", "hey", "hi",
    "eu", "aqui", "presente", "novo", "novato", "teste", "iptv", "p2p",
    "dreamtv", "hybrid", "player", "sistema",
}


def _extract_name_from_message(text: str) -> Optional[str]:
    """Try to pull a proper name from the client's WhatsApp message.

    Returns a Title-Cased first name (max 2 words) if we find one, else None.
    We're deliberately conservative — better to ask than to store the wrong
    name (which then appears in every future template).
    """
    if not text:
        return None
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = m.group(1).strip()
            # Reject obviously non-name words
            first_word = candidate.split()[0].lower()
            if first_word in _NOT_A_NAME:
                continue
            if len(first_word) < 2 or len(first_word) > 20:
                continue
            # Title Case, keep max 2 words (first + last)
            words = candidate.split()[:2]
            return " ".join(w.capitalize() for w in words)
    return None


# Awaiting-name state — set when we need a real name before creating a trial.
_pending_name: dict[str, dict] = {}
_NAME_STATE_TTL = 15 * 60  # 15 minutes to answer


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
    from services.phone_extractor import br_canonical
    if "@" in s:
        return br_canonical(s.split("@")[0])
    return br_canonical(s)


async def process_incoming_message(
    phone: str,
    body: str,
    from_me: bool = False,
    name: Optional[str] = None,
    real_phone: Optional[str] = None,
):
    """Handle a message from Node service."""
    phone_clean = normalize_phone(phone)
    # Real phone extracted from Contact by Node service — critical for @lid
    # chats where phone_clean = "12345@lid" carries no real number. We use
    # this to (a) send to painel as `whatsapp` on trial creation so
    # `reseller_notes` gets set, and (b) fill customers.whatsapp so admins
    # can identify LID users.
    #
    # Defensive validation: LID identifiers are typically 15-18+ digits and
    # look like phones but aren't. E.164 real phones cap at 15 digits and
    # in practice WhatsApp phones are 10-13 (BR: 12-13). Reject anything
    # outside 8-14 digits to avoid registering an LID as a phone.
    real_phone_clean = ""
    if real_phone:
        digits = "".join(c for c in str(real_phone) if c.isdigit())
        if 8 <= len(digits) <= 14:
            from services.phone_extractor import _clean
            real_phone_clean = _clean(digits) if len(digits) >= 10 else digits
        else:
            logger.warning(
                "Rejecting suspect real_phone=%r (digits=%d) — likely an "
                "LID leaking through, not a real phone",
                real_phone, len(digits),
            )

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

    # If Node resolved a real phone for this LID chat, backfill it onto the
    # customer row so admins see the actual number in the UI + so we can send
    # it to painel `reseller_notes` on trial creation.
    if real_phone_clean and phone_clean.endswith("@lid"):
        existing_wa = (customer.get("whatsapp") or "").strip()
        # Only backfill if the current value differs AND admin hasn't manually
        # locked the whatsapp field (whatsapp_locked=1 → admin overrode it).
        if existing_wa != real_phone_clean and not customer.get("whatsapp_locked"):
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE customers SET whatsapp = ?, updated_at = ? WHERE id = ? "
                        "AND (whatsapp_locked IS NULL OR whatsapp_locked = 0)",
                        (real_phone_clean, now_iso(), customer["id"]),
                    )
                    await db.commit()
                customer["whatsapp"] = real_phone_clean
                logger.info(
                    "Backfilled real phone %s onto LID customer %s (was %r)",
                    real_phone_clean, customer["id"], existing_wa,
                )
            except Exception:
                logger.exception("Failed to backfill real phone for %s", customer["id"])

    text = (body or "").strip()
    logger.info(
        "process_incoming: phone=%s from_me=%s text=%r customer=%s",
        phone_clean, from_me, text[:80], customer["id"],
    )

    if not text:
        return

    # ---------- Pending NAME follow-up ----------
    # We previously asked the client for their name (because we couldn't
    # parse one from their prior message). Their next reply IS the name.
    if not from_me and phone_clean in _pending_name:
        state = _pending_name[phone_clean]
        if now_ts - state["started_at"] > _NAME_STATE_TTL:
            _pending_name.pop(phone_clean, None)
        else:
            # Accept first 1-2 words as the name; sanity-check length.
            candidate = " ".join(text.strip().split()[:2])
            if 2 <= len(candidate) <= 40 and candidate.split()[0].lower() not in _NOT_A_NAME:
                proper = " ".join(w.capitalize() for w in candidate.split())
                await _update_customer_name(state["customer_id"], proper)
                customer["name"] = proper
                # Re-load the template and fire the trial.
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    cur = await db.execute(
                        "SELECT * FROM command_templates WHERE id = ? AND enabled = 1",
                        (state["template_id"],),
                    )
                    row = await cur.fetchone()
                _pending_name.pop(phone_clean, None)
                if row:
                    await _run_trial_creation(customer, dict(row), state.get("mac"), phone_clean)
                return
            # Not a plausible name — ask once more, then give up.
            await whatsapp_client.send_message(
                phone_clean,
                "Não entendi. Me diz seu *primeiro nome* por gentileza, "
                "só o nome (ex: *João*). 🙏",
            )
            await save_message(phone_clean, "AWAITING_NAME_RETRY", "out", customer["id"])
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
                f"{_mac_format_help(state.get('system_type'))}\n\n"
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
            # Use inferred system_type so DreamTV gets the "corner-of-screen" hint
            # while Hybrid/MAG boxes get the settings-menu hint.
            inferred_sys = _infer_system_type(
                matched.get("trigger_command", ""),
                matched.get("name", ""),
                matched.get("system_type") or "",
            )
            _pending_mac[phone_clean] = {
                "template_id": matched["id"],
                "attempts": 0,
                "started_at": now_ts,
                "customer_id": customer["id"],
                "system_type": inferred_sys,
            }
            label = "DreamTV" if inferred_sys == "iptv" else inferred_sys.upper()
            await whatsapp_client.send_message(
                phone_clean,
                f"📺 Para criar seu teste {label} preciso do endereço MAC do seu aparelho.\n\n"
                f"📱 Formato: `AA:BB:CC:DD:EE:FF`\n"
                f"{_mac_where_to_find(inferred_sys)}\n\n"
                f"Você tem {_MAX_MAC_ATTEMPTS} tentativas para enviar o MAC correto."
            )
            await save_message(phone_clean, "AWAITING_MAC", "out", customer["id"])
            return

    # ---- Client name resolution ----
    # 1) Try to pull a name from THIS message ("meu nome é João", "sou o Pedro", etc.)
    # 2) Fall back to the WhatsApp profile name (customer["name"] from `name`).
    # 3) If we still have nothing (or only the phone number), ask before
    #    firing the trial. Never store the raw phone/JID as the client name.
    parsed_name = _extract_name_from_message(text)
    stored_name = (customer.get("name") or "").strip()
    stored_is_placeholder = (
        not stored_name
        or stored_name == phone_clean
        or stored_name.replace("+", "").replace(" ", "").isdigit()
    )
    if parsed_name:
        # Prefer what the client just typed — most accurate signal.
        await _update_customer_name(customer["id"], parsed_name)
        customer["name"] = parsed_name
    elif stored_is_placeholder:
        # Ask for the name before creating a trial (only for client messages,
        # not admin-triggered creations).
        if not from_me:
            _pending_name[phone_clean] = {
                "template_id": matched["id"],
                "mac": mac,
                "customer_id": customer["id"],
                "started_at": now_ts,
            }
            await whatsapp_client.send_message(
                phone_clean,
                "Olá! 👋 Antes de criar seu teste, me diz seu *primeiro nome* "
                "por gentileza? 😊",
            )
            await save_message(phone_clean, "AWAITING_NAME", "out", customer["id"])
            return

    await _run_trial_creation(customer, matched, mac, phone_clean)


async def _run_trial_creation(customer: dict, matched: dict, mac: Optional[str], phone_clean: str):
    """Actually invoke painel.create_trial, persist result, send response to client.

    Extracted from process_incoming_message so the MAC-retry flow can call it
    once a valid MAC arrives on a subsequent message.
    """
    # ---- Defensive normalization of system_type ----
    # In production we saw templates whose trigger_command / name clearly say
    # "hybrid" or "dream tv" but whose `system_type` DB column was set to
    # "iptv" by mistake — result: Hybrid clients ended up as plain DreamTV
    # trials and vice-versa. Infer from name+trigger when they contradict.
    raw_system = (matched.get("system_type") or "").lower().strip()
    inferred_system = _infer_system_type(
        matched.get("trigger_command") or "",
        matched.get("name") or "",
        raw_system,
    )
    if inferred_system != raw_system:
        logger.warning(
            "Template %r has system_type=%r but trigger/name says %r — using inferred value. "
            "Fix the template in the admin panel to remove this warning.",
            matched.get("name"), raw_system, inferred_system,
        )
    system_type = inferred_system

    await log_activity("bot_trigger", f"Comando '{matched['trigger_command']}' de {phone_clean} (system={system_type})", customer["id"], "info")
    logger.info(
        "Creating trial via painel.fun: system=%s mac=%s customer=%s",
        system_type, mac, customer["id"],
    )

    try:
        # For LID chats phone_clean has no real digits. Prefer the real phone
        # we backfilled onto customer.whatsapp earlier (from msg.getContact()).
        # For non-LID chats phone_clean IS the number so use it as-is.
        whatsapp_for_painel = phone_clean
        if phone_clean.endswith("@lid"):
            stored = (customer.get("whatsapp") or "").strip()
            # `stored` may still be the raw LID (`123@lid`) if we never got a
            # real number — treat that as "no phone" so painel doesn't receive
            # a fake LID-suffix number.
            if stored.endswith("@lid") or not stored:
                whatsapp_for_painel = ""
            else:
                whatsapp_for_painel = "".join(c for c in stored if c.isdigit())

        # Call painel.fun to create trial
        result = await painel.create_trial(
            system_type=system_type,
            mac=mac,
            name=customer.get("name") or phone_clean,
            whatsapp=whatsapp_for_painel,
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
                (trial_id, customer["id"], system_type, mac,
                 painel_user, painel_pass, trial_user_id, expires, now_iso(),
                 json.dumps(result)),
            )
            # Update customer system_type + credentials
            await db.execute(
                "UPDATE customers SET system_type = ?, mac = COALESCE(?, mac), painel_username = ?, painel_password = ?, expires_at = ?, updated_at = ? WHERE id = ?",
                (system_type, mac, painel_user, painel_pass, expires, now_iso(), customer["id"])
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
        # When payment_link_provider=painel, replace with pagme.xyz direct link
        try:
            from services.pay_link import resolve_pay_link
            checkout_link = await resolve_pay_link(payment_ref_id, checkout_link)
        except Exception:
            pass

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
                        description=f"Assinatura {system_type.upper()} — {months} {'mês' if months == 1 else 'meses'}",
                        redirect_url=f"{public_base}/pay/{payment_ref_id}?ok=1" if public_base else None,
                        webhook_url=await infinitepay.build_webhook_url(public_base) if public_base else None,
                        customer_name=customer.get("name"),
                        customer_phone=phone_clean if not phone_clean.endswith("@lid") else None,
                    )
                    pay_links_by_plan[months] = result_link["url"]
                except Exception as pay_err:
                    logger.warning("Failed to generate InfinitePay link for %dm: %s", months, pay_err)

        response = (template
                    .replace("{system_type}", system_type.upper())
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

        # If the command template has an attached image, send it as media
        # with the response as caption. Otherwise plain text.
        image_url = matched.get("image_url") or None
        if image_url:
            # Convert relative /api/uploads/... to absolute URL so the
            # WhatsApp service can fetch it.
            if image_url.startswith("/"):
                pub = await _get_setting("public_base_url", "")
                if pub:
                    image_url = pub.rstrip("/") + image_url
        await whatsapp_client.send_message(phone_clean, response, image_url=image_url)
        await save_message(phone_clean, response, "out", customer["id"])
        await log_activity("trial_created", f"Teste {system_type} criado para {phone_clean}", customer["id"], "success", result)

        # Schedule 1h + 3h reminders
        try:
            from services.reminders import schedule as _schedule_reminder
            ctx = {
                "name": customer.get("name") or "",
                "user": painel_user or "",
                "pass": painel_pass or "",
                "expires": expires or "",
                "system_type": (system_type or "").upper(),
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
        # BUT ALSO synchronously inject the trial into the cache so /pay/{id}
        # works instantly from any browser worldwide — no waiting for the
        # 30-90s Turnstile-gated painel refresh.
        try:
            from routers.painel_users import upsert_users_in_cache, refresh_cache_task
            # Build a painel-user-shaped record from the trial result
            trial_user_record = {
                **(result if isinstance(result, dict) else {}),
                "id": trial_user_id or result.get("id"),
                "username": painel_user or result.get("username"),
                "full_name": customer.get("name") or "",
                "whatsapp": phone_clean,
                "is_trial": 1,
                "system": {"iptv": 1, "p2p": 2, "hybrid": 3}.get(system_type, 1),
            }
            await upsert_users_in_cache([trial_user_record])
            logger.info("Injected trial %s into cache for instant /pay/%s lookup",
                        trial_user_id, trial_user_id)
            import asyncio as _asyncio
            _asyncio.create_task(refresh_cache_task())
        except Exception:
            logger.exception("Failed to inject trial into painel users cache")

        # Also persist to MongoDB Atlas so /pay/{painel_id} works globally
        # across all environments (Raspberry Pi, preview, prod).
        try:
            from services import mongo_store
            await mongo_store.upsert_customer({
                "_id": trial_user_id,
                "id": int(trial_user_id) if trial_user_id.isdigit() else trial_user_id,
                "painel_username": painel_user,
                "painel_password": painel_pass,
                "full_name": customer.get("name") or "",
                "whatsapp": phone_clean,
                "system_type": system_type,
                "is_trial": True,
                "mac": mac,
                "exp_date_iso": expires,
            })
            logger.info("Persisted trial %s to MongoDB Atlas", trial_user_id)
        except Exception:
            logger.exception("Failed to persist trial to MongoDB Atlas (non-fatal)")

    except Exception as e:
        logger.exception("Failed to create trial: %s", e)
        err_str = str(e) or "erro desconhecido"
        err_lower = err_str.lower()
        retry_hint = "👉 Envie um dos comandos que você usou novamente."

        # Friendly error mapping: painel.fun sometimes returns validation
        # errors on auto-generated fields (password, username collisions,
        # etc.). These are 100% retryable — the next attempt uses a freshly
        # generated random password/username and usually succeeds.
        friendly = None
        if "password" in err_lower and ("invalid" in err_lower or "format" in err_lower):
            friendly = (
                "⚠️ Poxa, tivemos um probleminha rápido gerando seu acesso. 🤖\n\n"
                f"Por gentileza, {retry_hint.lower()}"
            )
        elif "username" in err_lower and ("taken" in err_lower or "exists" in err_lower
                                          or "duplic" in err_lower or "unique" in err_lower):
            friendly = (
                "⚠️ Já existe um usuário parecido. Vou gerar outro pra você! 🤖\n\n"
                f"{retry_hint}"
            )
        elif "mac" in err_lower and ("invalid" in err_lower or "format" in err_lower
                                     or "duplic" in err_lower):
            friendly = (
                "⚠️ Não consegui validar esse MAC. Confira se digitou certo "
                "(formato *AA:BB:CC:DD:EE:FF*) e envie novamente. 📱"
            )
        elif "credit" in err_lower or "saldo" in err_lower or "insufficient" in err_lower:
            friendly = (
                "⚠️ Estamos sem créditos no painel no momento. Nossa equipe "
                "já foi avisada — tente novamente em alguns minutos. 🙏"
            )
        elif "429" in err_str or "rate" in err_lower or "throttl" in err_lower:
            friendly = (
                "⚠️ Muitas solicitações no momento. Aguarde 1 minuto e tente "
                f"novamente por gentileza. ⏱️\n\n{retry_hint}"
            )
        elif "timeout" in err_lower or "timed out" in err_lower:
            friendly = (
                "⚠️ O painel está lento agora. Por gentileza, aguarde uns "
                f"segundos e tente novamente. ⏱️\n\n{retry_hint}"
            )

        if friendly:
            client_msg = friendly
        else:
            # Fallback: keep it concise and human — no technical details.
            client_msg = (
                "❌ Não consegui criar seu teste agora. 🤖\n\n"
                f"Por gentileza, {retry_hint.lower()}\n\n"
                "Se continuar não funcionando, chama a gente aqui que a "
                "equipe te ajuda. 💬"
            )

        await whatsapp_client.send_message(phone_clean, client_msg)

        # Admin alert — with the full technical detail so we can debug.
        try:
            from services.notifier import send_admin_alert
            await send_admin_alert(
                "⚠️ *Falha ao criar teste*\n\n"
                f"👤 Cliente: {customer.get('name') or phone_clean}\n"
                f"📱 WhatsApp: {phone_clean}\n"
                f"🎯 Sistema: {system_type.upper()}\n"
                f"🔧 MAC: {mac or '-'}\n"
                f"❌ Motivo técnico: {err_str[:300]}"
            )
        except Exception:
            logger.exception("Failed to notify admin about trial error")

        await log_activity("trial_error", str(e)[:500], customer["id"], "error")
