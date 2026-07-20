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
                confirmation_token TEXT,
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

            CREATE TABLE IF NOT EXISTS notification_templates (
                id TEXT PRIMARY KEY,
                event_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                image_url TEXT,
                enabled INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS painel_users_cache (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scheduled_reminders (
                id TEXT PRIMARY KEY,
                event_key TEXT NOT NULL,
                phone TEXT NOT NULL,
                context TEXT NOT NULL,
                send_at TEXT NOT NULL,
                sent INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reminders_pending ON scheduled_reminders(sent, send_at);

            CREATE TABLE IF NOT EXISTS notification_deliveries (
                id TEXT PRIMARY KEY,
                event_key TEXT NOT NULL,
                phone TEXT NOT NULL,
                body TEXT NOT NULL,
                image_url TEXT,
                customer_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_retry_at TEXT,
                last_error TEXT,
                sent_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_deliveries_status ON notification_deliveries(status, next_retry_at);
            CREATE INDEX IF NOT EXISTS idx_deliveries_customer ON notification_deliveries(customer_id, created_at);
            """
        )
        await db.commit()

        # Seed default notification templates
        default_notifs = [
            {
                "event_key": "expiration_7d",
                "title": "Vencimento em 7 dias",
                "body": "Olá {name}! 👋\n\nSeu plano vence em *7 dias* ({expires_at}).\n\n{discount_line}Renove agora:\n{pay_link}",
                "image_url": "",
            },
            {
                "event_key": "expiration_3d",
                "title": "Vencimento em 3 dias",
                "body": "Olá {name}! 👋\n\nSeu plano vence em *3 dias* ({expires_at}).\n\nRenove agora e ganhe 5% de desconto no Pix:\n{pay_link}\n\nQualquer dúvida é só chamar aqui! 😉",
                "image_url": "",
            },
            {
                "event_key": "expiration_1d",
                "title": "Vencimento amanhã",
                "body": "⚠️ Olá {name}!\n\nSeu plano vence *amanhã* ({expires_at}).\n\nRenove agora para não perder o acesso:\n{pay_link}",
                "image_url": "",
            },
            {
                "event_key": "expiration_0d",
                "title": "Venceu hoje",
                "body": "🔴 Olá {name}, seu plano *venceu hoje*.\n\nRenove agora para reativar o acesso:\n{pay_link}",
                "image_url": "",
            },
            {
                "event_key": "expired_1d",
                "title": "Vencido há 1 dia",
                "body": "Olá {name}, seu plano está vencido há *1 dia*. 😢\n\nQue tal renovar agora e voltar a assistir?\n{pay_link}",
                "image_url": "",
            },
            {
                "event_key": "expired_3d",
                "title": "Vencido há 3 dias",
                "body": "Ei {name}, sentimos sua falta! Seu plano está vencido há *3 dias*.\n\nRenove pelo link e volte já a assistir:\n{pay_link}",
                "image_url": "",
            },
            {
                "event_key": "expired_7d",
                "title": "Vencido há 7 dias",
                "body": "{name}, faz uma semana que seu plano venceu.\n\nQuer voltar? Renove agora com condição especial:\n{pay_link}",
                "image_url": "",
            },
            {
                "event_key": "renewal_success",
                "title": "Renovação confirmada",
                "body": "✅ Pagamento confirmado, {name}!\n\nSeu plano foi renovado por *{plan_months} mês(es)* e já está ativo até {new_expires_at}.\n\nObrigado pela preferência! 🎉",
                "image_url": "",
            },
            {
                "event_key": "trial_ready",
                "title": "Teste criado",
                "body": "✅ Teste {system_type} criado com sucesso!\n\n👤 Usuário: {user}\n🔑 Senha: {pass}\n⏰ Expira em: {expires}\n\nGostou? Já garanta seu plano:\n{pay_link}",
                "image_url": "",
            },
            {
                "event_key": "trial_1h_reminder",
                "title": "Lembrete 1h após teste",
                "body": "Oi {name}, já faz *1h* que você começou o teste do sistema {system_type}. 😊\n\nGostou da qualidade? Aproveita e já contrata seu plano com condição especial:\n{pay_link}\n\nSuas credenciais continuam ativas:\n👤 {user}  🔑 {pass}",
                "image_url": "",
            },
            {
                "event_key": "trial_expired",
                "title": "Teste finalizado (3h)",
                "body": "⏰ {name}, seu teste do sistema {system_type} chegou ao fim.\n\nGostou do que viu? Assine agora e continue assistindo sem interrupções:\n{pay_link}\n\nQualquer dúvida é só chamar! 💬",
                "image_url": "",
            },
        ]
        from datetime import datetime, timezone
        import uuid as _uuid
        for nt in default_notifs:
            await db.execute(
                "INSERT OR IGNORE INTO notification_templates (id, event_key, title, body, image_url, enabled, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (str(_uuid.uuid4()), nt["event_key"], nt["title"], nt["body"], nt["image_url"], datetime.now(timezone.utc).isoformat()),
            )
        await db.commit()

        # Seed default settings
        defaults = {
            "painel_username": "Rithiele2026",
            "painel_password": "Rithi0518",
            "painel_base_url": "https://api.controle.fit",
            "twocaptcha_key": "c3233ff53fddf3e816b0cf78c2ccef61",
            "turnstile_sitekey": "0x4AAAAAACFhU7XJduqvbHH2",
            "turnstile_pageurl": "https://painel.fun/login",
            "infinitepay_handle": "",
            "notification_days": "7,3,1,0,-1,-3,-7",
            "trial_package_id": "61",
            "public_base_url": "https://whatsflow.zeferius.com",
            "timezone": "America/Sao_Paulo",
            "plan_price_1m": "35,00",
            "plan_price_3m": "90,00",
            "plan_price_6m": "160,00",
            "plan_price_12m": "280,00",
            "admin_whatsapp": "",
            "infinitepay_webhook_secret": "",
            # Discount for clients who pay ON THE SAME DAY the 7-day reminder was sent.
            # Toggled and % set by admin; expires end-of-day automatically since the
            # 7d reminder idempotency key is dated.
            "discount_7d_enabled": "false",
            "discount_7d_percent": "5",
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
        # Migration: add confirmation_token to payments (used by /pay/{id}?ok=1&t=<token>)
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN confirmation_token TEXT")
        except Exception:
            pass
        # Migration: add transaction_nsu to payments — InfinitePay generates a
        # different transaction_nsu per capture, so the SAME checkout link can
        # be paid multiple times (each triggering a new renewal). We use this
        # column as the true idempotency key, not order_nsu.
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN transaction_nsu TEXT")
        except Exception:
            pass
        # Receipt URL from InfinitePay webhook (payload.receipt_url) — shown
        # on /pay/{id} so the client can see proof of their own payment.
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN receipt_url TEXT")
        except Exception:
            pass
        # Discount fields — populated when a payment is created within the same
        # calendar day the 7-day reminder went out (if `discount_7d_enabled` is on).
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN discount_percent INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN original_amount_cents INTEGER")
        except Exception:
            pass
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_txn_nsu ON payments(transaction_nsu)")
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
