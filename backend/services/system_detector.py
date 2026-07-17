"""Detect system_type (iptv | p2p | hybrid) for a painel.fun user record.

Painel.fun doesn't expose a clean `system_type` field. We combine multiple
signals to classify each user:

  1. `package_id` reverse-lookup against known IPTV / P2P / hybrid packages.
  2. Structured fields (`system_type`, `type`, `product`, `package_name`, ...).
  3. Free-text notes / description scanning for keywords.
  4. Heuristic: presence of MAC address strongly suggests IPTV.
"""
import re
from typing import Optional

# From backend/services/painel.py PACKAGE_IDS
_IPTV_PACKAGES = {17, 43, 56, 58}
_P2P_PACKAGES = {17, 42, 55, 57}
_HYBRID_PACKAGES = {17, 42, 55, 57}

# Ambiguous packages (present in multiple systems) — we need other signals
_AMBIGUOUS = {17, 42, 55, 57}
# Unique IPTV markers
_IPTV_ONLY = {43, 56, 58}

_IPTV_KEYWORDS = ("iptv", "dream", "smarters", "xtream", "set-top", "settop", "tv box", "tvbox")
_P2P_KEYWORDS = ("p2p", "braz", "brazuca", "sopcast", "peer")
_HYBRID_KEYWORDS = ("hybrid", "híbrido", "hibrido", "duo", "combo")

_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}")


def _pick(user: dict, keys: tuple) -> str:
    for k in keys:
        v = user.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _scan_keywords(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    # Order: hybrid first (most specific), then iptv, then p2p
    if any(k in t for k in _HYBRID_KEYWORDS):
        return "hybrid"
    if any(k in t for k in _IPTV_KEYWORDS):
        return "iptv"
    if any(k in t for k in _P2P_KEYWORDS):
        return "p2p"
    return None


def detect_system_type(user: dict) -> Optional[str]:
    """Return 'iptv' | 'p2p' | 'hybrid' | None."""
    if not isinstance(user, dict):
        return None

    # 1. Package ID reverse lookup (skipping ambiguous ids)
    pid = user.get("package_id") or user.get("current_package_id") or user.get("plan_id")
    try:
        pid_int = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid_int = None

    if pid_int is not None and pid_int not in _AMBIGUOUS:
        if pid_int in _IPTV_ONLY:
            return "iptv"
        if pid_int in _P2P_PACKAGES:
            return "p2p"
        if pid_int in _HYBRID_PACKAGES:
            return "hybrid"

    # 2. Structured fields
    structured = _pick(user, (
        "system_type", "type", "system", "product", "product_name",
        "package_name", "package", "plan_name", "plan", "server",
    ))
    kw = _scan_keywords(structured)
    if kw:
        return kw

    # 3. Free-text notes / description
    for k in ("notes", "notas", "note", "obs", "observation", "observacao",
              "description", "descricao", "info", "comment", "comments"):
        v = user.get(k)
        if v:
            kw = _scan_keywords(str(v))
            if kw:
                return kw

    # 4. Nested meta / custom_fields
    for k in ("meta", "metadata", "data", "custom_fields", "profile"):
        sub = user.get(k)
        if isinstance(sub, dict):
            r = detect_system_type(sub)
            if r:
                return r
        if isinstance(sub, list):
            for item in sub:
                if isinstance(item, dict):
                    combined = " ".join(str(v) for v in item.values() if v)
                    kw = _scan_keywords(combined)
                    if kw:
                        return kw

    # 5. Heuristic: MAC address present → IPTV (unless already classified)
    mac = user.get("mac") or user.get("mac_address")
    if mac and _MAC_RE.search(str(mac)):
        return "iptv"
    # Sometimes MAC is embedded in notes
    for k in ("notes", "notas", "obs", "description"):
        v = user.get(k)
        if v and _MAC_RE.search(str(v)):
            return "iptv"

    # 6. Fallback: ambiguous package_id → best guess (iptv is most common)
    if pid_int in _AMBIGUOUS:
        return "iptv"

    return None
