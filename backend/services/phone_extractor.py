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
      - If digits already start with 55 and length is 12-13 → BR keep as-is.
      - If bare digits are 10 or 11 → assume Brazilian local, prepend 55
        (system is primary-BR; ambiguity resolved in favour of BR).
      - Bare digits 12-15 → assume already has a country code, keep as-is.
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

    # 2) Already BR-prefixed (55 + 10/11 local digits)
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits

    # 3) Bare BR local (10 = fixed, 11 = mobile) → prepend 55
    if len(digits) in (10, 11):
        return "55" + digits

    # 4) 12-15 digits without a `+` — assume already has a country code
    #    (e.g. `34612345678` = Spain, `447700900123` = UK). Keep as-is.
    if 12 <= len(digits) <= 15:
        return digits

    # 5) Too short (<10) or too long (>15) — leave untouched.
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
