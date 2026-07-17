"""Extract WhatsApp phone number from painel.fun user records.

The panel stores the phone inside free-text fields (notes/notas/obs/etc.),
not in a dedicated column. This module normalizes extraction across all
possible field names + regex-parses Brazilian phone numbers from free text.
"""
import re
from typing import Optional

# Matches Brazilian phone numbers with tolerant formatting:
#   +55 (11) 9 8765-4321
#   5511987654321
#   11987654321
#   (11) 98765-4321
#   11 9 8765 4321
# Captures 10 or 11 local digits (with optional 55 country code).
_PHONE_RE = re.compile(
    r"(?:\+?55[\s\-\.]?)?"        # optional country code
    r"\(?(\d{2})\)?[\s\-\.]?"     # DDD
    r"(9?[\s\-\.]?\d{4})[\s\-\.]?" # first block (mobile has extra 9)
    r"(\d{4})"                     # last 4
)

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


def _clean(number: str) -> str:
    """Return only digits, prepending 55 if missing and length looks Brazilian."""
    digits = re.sub(r"\D", "", number)
    if not digits:
        return ""
    # If it already starts with 55 and length >= 12 (55 + 10/11 digits) => ok
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    # Local (10 or 11 digits) => prepend 55
    if len(digits) in (10, 11):
        return "55" + digits
    return digits


def _match_in_text(text: str) -> Optional[str]:
    if not text:
        return None
    for m in _PHONE_RE.finditer(str(text)):
        candidate = m.group(0)
        cleaned = _clean(candidate)
        # Sanity: Brazilian number is 12 or 13 digits (55 + 10 or 11)
        if len(cleaned) in (12, 13):
            return cleaned
    return None


def extract_whatsapp(user: dict) -> Optional[str]:
    """Extract a WhatsApp phone number from a painel.fun user record.

    Strategy:
      1. Structured fields first (whatsapp, phone, ...).
      2. Free-text notes/observation fields — regex-scan for BR numbers.
      3. Fallback: scan every string value on the record for a number.
    """
    if not isinstance(user, dict):
        return None

    # 1. Structured
    for k in STRUCTURED_FIELDS:
        v = user.get(k)
        if v:
            found = _match_in_text(str(v)) or _clean(str(v))
            if found and len(found) in (12, 13):
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
                        if found and len(found) in (12, 13):
                            return found

    # 4. Last resort: scan every string value on the top-level record
    for v in user.values():
        if isinstance(v, str) and len(v) > 5 and len(v) < 500:
            found = _match_in_text(v)
            if found:
                return found

    return None
