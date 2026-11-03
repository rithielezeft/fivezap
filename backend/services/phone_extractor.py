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

# ISO-3166-1 alpha-2 country code → E.164 country calling code.
# Cover the most common markets the app sees. Extended when needed.
ISO_TO_CC = {
    "BR": "55",  "US": "1",   "CA": "1",   "MX": "52",  "AR": "54",  "CO": "57",
    "CL": "56",  "PE": "51",  "UY": "598", "PY": "595", "BO": "591", "VE": "58",
    "PT": "351", "ES": "34",  "FR": "33",  "IT": "39",  "DE": "49",  "GB": "44",
    "UK": "44",  "IE": "353", "NL": "31",  "BE": "32",  "CH": "41",  "AT": "43",
    "GR": "30",  "PL": "48",  "RO": "40",  "TR": "90",  "RU": "7",
    "IN": "91",  "CN": "86",  "JP": "81",  "KR": "82",  "AU": "61",  "NZ": "64",
    "ZA": "27",  "AE": "971", "SA": "966",
}

def _iso_or_name_to_cc(value: str) -> Optional[str]:
    """Given 'BR', 'br', 'Brazil', 'Brasil', 'US', 'USA', return the calling code."""
    if not value:
        return None
    v = value.strip().upper()
    if v in ISO_TO_CC:
        return ISO_TO_CC[v]
    # Reverse-lookup a few full names
    name_aliases = {
        "BRAZIL": "55", "BRASIL": "55",
        "UNITED STATES": "1", "USA": "1", "ESTADOS UNIDOS": "1",
        "PORTUGAL": "351", "SPAIN": "34", "ESPANA": "34", "ESPAÑA": "34",
        "FRANCE": "33", "GERMANY": "49", "UNITED KINGDOM": "44",
        "ARGENTINA": "54", "MEXICO": "52", "COLOMBIA": "57", "CHILE": "56",
    }
    return name_aliases.get(v)


# Matches phone numbers with tolerant formatting, including international:
#   +34 612 345 678
#   +351 912345678
#   +1 (555) 123-4567
#   5511987654321
#   +55 (11) 9 8765-4321
_PHONE_RE = re.compile(
    r"\+?\d[\d\s\-\.\(\)]{7,20}\d"
)


def _clean(number: str, country_hint: Optional[str] = None) -> str:
    """Return the phone as digits-only, ready for WhatsApp Web JID format.

    Rules:
      - If input has `+` → keep digits as-is (already E.164, respects the
        user's explicit country code — Spain, Portugal, USA, etc.).
      - Bare digits 12-15 → assume already has a country code, keep as-is.
      - Bare digits 10 or 11 → prepend the country code:
          * `country_hint` (ISO like 'US', 'BR', or E.164 code like '1', '55')
            takes highest priority — used when we know the client's country
            from painel.fun data.
          * Otherwise fall back to the admin-configured `default_country_code`
            setting (default "55" for Brazil).
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
        return br_canonical(digits)

    # 2) Already E.164 (12-15 digits) — has a country code, keep untouched.
    if 12 <= len(digits) <= 15:
        return br_canonical(digits)

    # 3) Bare local number (10-11 digits) → resolve country code.
    if len(digits) in (10, 11):
        cc: Optional[str] = None
        # Priority 1: explicit hint from painel data (per-client country)
        if country_hint:
            hint_digits = re.sub(r"\D", "", str(country_hint))
            if hint_digits:
                cc = hint_digits
            else:
                cc = _iso_or_name_to_cc(country_hint)
        # Priority 2: admin's global default
        if not cc:
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
        return br_canonical(cc + digits)

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


def _match_in_text(text: str, country_hint: Optional[str] = None) -> Optional[str]:
    if not text:
        return None
    for m in _PHONE_RE.finditer(str(text)):
        candidate = m.group(0)
        cleaned = _clean(candidate, country_hint)
        # Accept anything with a plausible international length (10-15 digits).
        if 10 <= len(cleaned) <= 15:
            return cleaned
    return None


def _plausible_length(digits: str) -> bool:
    return bool(digits) and 10 <= len(digits) <= 15


def _extract_country_hint(user: dict) -> Optional[str]:
    """Find a country identifier in the user record. Painel.fun and similar
    tools may use different keys — check the most common ones."""
    for k in ("country", "country_code", "country_iso", "pais",
              "país", "nationality", "nacionalidade"):
        v = user.get(k)
        if v:
            s = str(v).strip()
            if s:
                return s
    return None


def extract_whatsapp(user: dict) -> Optional[str]:
    """Extract a WhatsApp phone number from a painel.fun user record.

    Strategy:
      1. Structured fields first (whatsapp, phone, ...).
      2. Free-text notes/observation fields — regex-scan for phone numbers.
      3. Fallback: scan every string value on the record for a number.

    Whenever the user record has a `country` / `country_code` / `pais`
    field, that country's calling code is used to prepend to bare local
    numbers (so a `5551234567` on a US client becomes `15551234567` even
    if the global default is BR).
    """
    if not isinstance(user, dict):
        return None

    country_hint = _extract_country_hint(user)

    # 1. Structured
    for k in STRUCTURED_FIELDS:
        v = user.get(k)
        if v:
            found = _match_in_text(str(v), country_hint) or _clean(str(v), country_hint)
            if _plausible_length(found):
                return found

    # 2. Notes
    for k in NOTES_FIELDS:
        v = user.get(k)
        if v:
            found = _match_in_text(str(v), country_hint)
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


def br_canonical(digits: str) -> str:
    """Brazilian mobiles always stored WITH the 9th digit: 55 DDD 9XXXXXXXX.

    WhatsApp often reports old-format JIDs (55 31 8658-2251, 12 digits) for the
    same person who types 55 31 98658-2251 — without this the same client
    shows up as two numbers and lookups/notifications miss them."""
    d = re.sub(r"\D", "", str(digits or ""))
    if len(d) == 12 and d.startswith("55") and d[4] in "6789":
        return d[:4] + "9" + d[4:]
    return d


def br_variants(digits: str) -> list:
    """Both forms (with/without 9th digit) for matching legacy rows."""
    c = br_canonical(digits)
    out = [c]
    if len(c) == 13 and c.startswith("55") and c[4] == "9":
        out.append(c[:4] + c[5:])
    return out
