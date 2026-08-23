"""Extract WhatsApp phone number from painel.fun user records.

The panel stores the phone inside free-text fields (notes/notas/obs/etc.),
not in a dedicated column. This module normalizes extraction across all
possible field names + regex-parses phone numbers from free text.

International-aware: the same client base includes Brazil (+55), USA (+1),
Spain (+34), Portugal (+351), UK (+44), etc. We only prepend +55 when the
number is UNAMBIGUOUSLY a bare Brazilian local (10-11 digits, no `+`, no
recognized foreign country prefix).
"""
import re
from typing import Optional

# Matches phone numbers with tolerant formatting, including international:
#   +34 612 345 678
#   +351 912345678
#   +1 (555) 123-4567
#   5511987654321
#   +55 (11) 9 8765-4321
_PHONE_RE = re.compile(
    r"\+?\d[\d\s\-\.\(\)]{7,20}\d"
)


def _clean(number: str) -> str:
    """Return the phone as digits-only, ready for WhatsApp Web JID format.

    Rules:
      - If input has `+` → keep digits as-is (already E.164, respects the
        user's explicit country code — Spain, Portugal, USA, etc.).
      - Bare digits 12-15 → assume already has a country code, keep as-is.
      - Bare digits 10 or 11 → prepend the admin-configured
        `default_country_code` (Setting; default "55" for Brazil). Admins
        with international clients can change this to "1" (USA), "351"
        (Portugal), "34" (Spain), etc.
      - Anything else → keep digits (invalid length, let caller reject).
    """
    if not number:
        return ""
    raw = str(number)
    has_plus = "+" in raw
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""

    # 1) User passed `+` — respect their intent, don't prepend anything.
    if has_plus:
        return digits

    # 2) Already E.164 (12-15 digits) — has a country code, keep untouched.
    #    Common examples: 5511987654321 (BR), 447700900123 (UK),
    #    34612345678 (ES), 15551234567 (US).
    if 12 <= len(digits) <= 15:
        return digits

    # 3) Bare local number (10-11 digits) → prepend the admin-configured
    #    default country code. RESPECT country-specific length:
    #    - BR (55): 10 = fixed, 11 = mobile → both need prepending
    #    - USA/CA (1): 10 = local, 11 = already has "1" prefix → only prepend 10
    #    - PT (351): 9 = local → we only see 10-11 here, so 11 = already has 351? no
    #                 351 + 9 = 12 which falls into rule (2). So 10-11 = local.
    #    General rule: for 11-digit numbers, prepend only if the country code
    #    is BR (55). For other 1-digit country codes, 11 digits = already E.164.
    if len(digits) in (10, 11):
        try:
            from database import get_setting_sync
            cc = (get_setting_sync("default_country_code") or "55").strip()
            cc = re.sub(r"\D", "", cc) or "55"
        except Exception:
            cc = "55"

        # 11-digit heuristic: if the country code is 1 digit long
        # (USA=1, KZ=7, RU=7) AND our input is 11 digits AND starts with
        # that country code, assume E.164 (don't double-prefix).
        if len(digits) == 11 and len(cc) == 1 and digits.startswith(cc):
            return digits
        # 11-digit + non-BR country code: 11 digits already includes it.
        if len(digits) == 11 and cc not in ("55",):
            return digits
        return cc + digits

    # 4) Too short (<10) or too long (>15) — leave untouched.
    return digits

# Fields on painel.fun where the phone might live (structured OR free text)
STRUCTURED_FIELDS = (
    "as_number",        # painel.fun normalized WhatsApp (+5511987654321)
    "whatsapp", "phone", "telephone", "mobile", "celular", "cell",
)
NOTES_FIELDS = (
    "reseller_notes",   # painel.fun reseller notes (free-text WhatsApp)
    "notes", "note", "notas", "nota",
    "obs", "observation", "observations", "observacao", "observacoes",
    "description", "descricao", "comment", "comments", "comentario",
    "info", "extra", "extras", "custom", "custom_notes",
)


def _match_in_text(text: str) -> Optional[str]:
    if not text:
        return None
    for m in _PHONE_RE.finditer(str(text)):
        candidate = m.group(0)
        cleaned = _clean(candidate)
        # Accept anything with a plausible international length (10-15 digits).
        if 10 <= len(cleaned) <= 15:
            return cleaned
    return None


def _plausible_length(digits: str) -> bool:
    return bool(digits) and 10 <= len(digits) <= 15


def extract_whatsapp(user: dict) -> Optional[str]:
    """Extract a WhatsApp phone number from a painel.fun user record.

    Strategy:
      1. Structured fields first (whatsapp, phone, ...).
      2. Free-text notes/observation fields — regex-scan for phone numbers.
      3. Fallback: scan every string value on the record for a number.
    """
    if not isinstance(user, dict):
        return None

    # 1. Structured
    for k in STRUCTURED_FIELDS:
        v = user.get(k)
        if v:
            found = _match_in_text(str(v)) or _clean(str(v))
            if _plausible_length(found):
                return found

    # 2. Notes
    for k in NOTES_FIELDS:
        v = user.get(k)
        if v:
            found = _match_in_text(str(v))
            if found:
                return found

    # 3. Nested "meta"/"data"/"custom_fields" dicts commonly used by panels
    for k in ("meta", "metadata", "data", "custom_fields", "fields", "profile"):
        sub = user.get(k)
        if isinstance(sub, dict):
            r = extract_whatsapp(sub)
            if r:
                return r
        if isinstance(sub, list):
            # Custom fields sometimes shipped as [{key, value}]
            for item in sub:
                if isinstance(item, dict):
                    key = str(item.get("key") or item.get("name") or "").lower()
                    val = item.get("value") or item.get("content")
                    if val and (
                        "whatsapp" in key or "phone" in key or
                        "notas" in key or "obs" in key or "note" in key
                    ):
                        found = _match_in_text(str(val)) or _clean(str(val))
                        if _plausible_length(found):
                            return found

    # 4. Last resort: scan every string value on the top-level record
    for v in user.values():
        if isinstance(v, str) and 5 < len(v) < 500:
            found = _match_in_text(v)
            if found:
                return found

    return None
