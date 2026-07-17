"""SQLite database setup for WhatsFlow."""
import os
import aiosqlite
from pathlib import Path

ROOT_DIR = Path(__file__).parent
DB_PATH = os.environ.get("SQLITE_PATH", str(ROOT_DIR / "whatsflow.db"))


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                whatsapp TEXT NOT NULL,
                system_type TEXT NOT NULL,
                mac TEXT,
                painel_username TEXT,
                painel_password TEXT,
                current_package_id INTEGER,
                expires_at TEXT,
                status TEXT DEFAULT 'active',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_customers_whatsapp ON customers(whatsapp);
            CREATE INDEX IF NOT EXISTS idx_customers_status ON customers(status);
            CREATE INDEX IF NOT EXISTS idx_customers_expires ON customers(expires_at);

            CREATE TABLE IF NOT EXISTS trials (
                id TEXT PRIMARY KEY,
                customer_id TEXT,
                system_type TEXT NOT NULL,
                mac TEXT,
                painel_user TEXT,
                painel_pass TEXT,
                trial_user_id TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                raw_response TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_trials_customer ON trials(customer_id);

            CREATE TABLE IF NOT EXISTS command_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                trigger_command TEXT NOT NULL UNIQUE,
                system_type TEXT NOT NULL,
                requires_mac INTEGER DEFAULT 0,
                package_id INTEGER,
                response_template TEXT,
                enabled INTEGER DEFAULT 1,
                trigger_source TEXT DEFAULT 'both',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                customer_id TEXT,
                phone TEXT NOT NULL,
                message TEXT NOT NULL,
                direction TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone);
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);

            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                plan_months INTEGER NOT NULL,
                amount_cents INTEGER NOT NULL,
                package_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                infinitepay_url TEXT,
                order_nsu TEXT,
                paid_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id);
            CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);

            CREATE TABLE IF NOT EXISTS activity_logs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                customer_id TEXT,
                message TEXT NOT NULL,
                status TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_logs_created ON activity_logs(created_at);
            """
        )
        await db.commit()

        # Seed default settings
        defaults = {
            "painel_username": "Rithiele2026",
            "painel_password": "Rithi0518",
            "painel_base_url": "https://api.controle.fit",
            "twocaptcha_key": "c3233ff53fddf3e816b0cf78c2ccef61",
            "turnstile_sitekey": "0x4AAAAAAABkMYinukE_i92X",
            "turnstile_pageurl": "https://painel.fun",
            "infinitepay_handle": "",
            "notification_days": "3,1,0",
            "trial_package_id": "61",
            "public_base_url": "https://whatsflow.zeferius.com",
            "timezone": "America/Sao_Paulo",
            "plan_price_1m": "35,00",
            "plan_price_3m": "90,00",
            "plan_price_6m": "160,00",
            "plan_price_12m": "280,00",
        }
        for key, value in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        # Migration: add trigger_source column if missing
        try:
            await db.execute("ALTER TABLE command_templates ADD COLUMN trigger_source TEXT DEFAULT 'both'")
        except Exception:
            pass
        # Cleanup: remove old *_cents price keys (kept if you rely on them)
        await db.execute("DELETE FROM settings WHERE key IN ('plan_price_1m_cents','plan_price_3m_cents','plan_price_6m_cents','plan_price_12m_cents')")
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def get_all_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {row["key"]: row["value"] for row in rows}
