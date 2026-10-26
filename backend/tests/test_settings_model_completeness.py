"""Regression test: every settings field editable in the frontend Settings
page MUST be present in the SettingsUpdate Pydantic model. Otherwise Pydantic
silently drops unknown keys and the setting never persists.

Previously reported bugs:
- admin_whatsapp: change didn't persist
- discount_7d_enabled: change didn't persist
- discount_7d_percent: also missing from model
- infinitepay_webhook_secret: also missing
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


FRONTEND_SETTINGS = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "pages" / "Settings.jsx"


def _frontend_field_keys() -> set[str]:
    """Parse the FIELDS array in Settings.jsx and extract every `key: "..."`."""
    txt = FRONTEND_SETTINGS.read_text()
    m = re.search(r"const FIELDS\s*=\s*\[(.+?)\];", txt, re.S)
    assert m, "Could not locate FIELDS array in Settings.jsx"
    fields_block = m.group(1)
    keys = re.findall(r'key:\s*"([^"]+)"', fields_block)
    return set(keys)


def test_settings_update_model_covers_every_frontend_field():
    from models import SettingsUpdate

    frontend_keys = _frontend_field_keys()
    model_keys = set(SettingsUpdate.model_fields.keys())

    missing = frontend_keys - model_keys
    assert not missing, (
        f"Frontend Settings.jsx exposes fields that SettingsUpdate model "
        f"does NOT include, so PUT /api/settings silently drops them: {sorted(missing)}. "
        f"Add them to models.SettingsUpdate."
    )


def test_admin_whatsapp_and_discount_are_in_model():
    """Explicit sanity check for the fields reported by the user (bug report
    2026-02-22). If any of these are removed, this test warns loudly."""
    from models import SettingsUpdate

    fields = set(SettingsUpdate.model_fields.keys())
    required = {
        "admin_whatsapp",
        "discount_7d_enabled",
        "discount_7d_percent",
        "infinitepay_webhook_secret",
    }
    missing = required - fields
    assert not missing, f"Required settings missing from SettingsUpdate model: {missing}"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
