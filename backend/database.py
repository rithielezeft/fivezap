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
                image_url TEXT,
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

            CREATE TABLE IF NOT EXISTS coupons (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                discount_percent INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_coupons_code ON coupons(code);

            CREATE TABLE IF NOT EXISTS coupon_usages (
                id TEXT PRIMARY KEY,
                coupon_id TEXT NOT NULL,
                coupon_code TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                payment_id TEXT,
                phone TEXT,
                discount_percent INTEGER NOT NULL,
                receipt_url TEXT,
                painel_username TEXT,
                used_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_coupon_usages_customer ON coupon_usages(customer_id, used_at);
            CREATE INDEX IF NOT EXISTS idx_coupon_usages_coupon ON coupon_usages(coupon_id, used_at);
            """
        )
        await db.commit()

        # Seed default notification templates (shared source of truth so
        # the restore-defaults endpoint stays in sync with the initial seed).
        # The trial-related templates are kept inline here (not in the shared
        # module) because they aren't restorable via /restore-defaults — the
        # admin edits them and we don't want to override.
        from services.default_templates import DEFAULT_TEMPLATES
        default_notifs = list(DEFAULT_TEMPLATES) + [
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
        # Upgrade the first multi-login default (never edited) to the new layout.
        await db.execute(
            "UPDATE notification_templates SET body = ? WHERE event_key = 'renewal_success_multi' AND body IN (?, ?)",
            (next(t["body"] for t in DEFAULT_TEMPLATES if t["event_key"] == "renewal_success_multi"),
             "✅ Pagamento confirmado, {name}!\n\nSeus *{count} logins* foram renovados por *{plan_months} mês(es)*:\n{logins}\n\nObrigado pela preferência! 🎉",
             "✅ Pagamento confirmado! Obrigado, {name} 🎉\n\nSeus dados de acesso:\n\n{acessos}\n\n🍀 Trevo: {clovers} e {clover_coupons}\n\nSeu acesso já está renovado. Bom proveito! 😃\n\n{name}, não esqueça de fazer parte do nosso Canal: \nhttps://shre.ink/zeferius"),
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
            # Dedup — prevents sending the same template (event_key) to the
            # same phone twice within `dedup_window_minutes`. When disabled,
            # every enqueue always creates a new delivery row.
            "dedup_enabled": "true",
            "dedup_window_minutes": "60",
            # How often the Clientes page auto-refreshes from painel.fun.
            # Each refresh burns 2Captcha credits, so raising this saves $$.
            # Applied to both the background loop AND the cache-staleness
            # threshold used by the /api/painel/users endpoint.
            "painel_refresh_interval_seconds": "300",
            # Timezone for date display in the UI (dashboard, receipts,
            # customer page, etc.). Default = Brasília. Change here → the
            # frontend re-renders all dates in the selected TZ.
            "display_timezone": "America/Sao_Paulo",
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
        # Multi-provider / multi-account / multi-points checkout
        for col_sql in (
            "provider TEXT DEFAULT 'infinitepay'", "account_id TEXT", "extra_customer_ids TEXT",
            "mp_payment_id TEXT", "adult_channels INTEGER", "pix_qr_code TEXT",
            "pix_qr_base64 TEXT", "pix_ticket_url TEXT", "clovers INTEGER DEFAULT 0",
        ):
            try:
                await db.execute(f"ALTER TABLE payments ADD COLUMN {col_sql}")
            except Exception:
                pass
        # Attribution bucket — where did this payment click come from?
        # Values match the reminder event_key (expiration_7d, expiration_3d,
        # expiration_1d, expiration_0d, expired_Xd, trial_ready) or 'manual'
        # for admin-created links / 'direct' for links opened without ?ref=.
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN ref_bucket TEXT")
        except Exception:
            pass
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_ref ON payments(ref_bucket)")
        except Exception:
            pass
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_txn_nsu ON payments(transaction_nsu)")
        except Exception:
            pass
        # Coupon applied at checkout (nullable). Stored on the payment row so
        # the admin history + PublicPay page can show it (and so the webhook
        # can record `coupon_usages` on confirmation).
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN coupon_code TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN coupon_id TEXT")
        except Exception:
            pass
        # Track failed renewal attempts so a background retry loop can
        # auto-recover from transient painel.fun errors like
        # ERROR_NO_SLOT_AVAILABLE (reseller ran out of slots temporarily).
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN renewal_attempts INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN renewal_next_retry_at TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN renewal_last_error TEXT")
        except Exception:
            pass
        # Body-hash for cross-event-key dedup. Two different code paths may
        # produce the same rendered message body (e.g. expiration_3d vs a
        # manual bulk-send) — hashing the phone+body prevents sending twice.
        try:
            await db.execute("ALTER TABLE notification_deliveries ADD COLUMN body_hash TEXT")
        except Exception:
            pass
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_hash ON notification_deliveries(body_hash, created_at)")
        except Exception:
            pass
        # Coupon extensions: expiration timestamp + max uses limit.
        # discount_percent is stored as-is (SQLite REAL accepts float even
        # if the column was declared INTEGER — no migration needed).
        try:
            await db.execute("ALTER TABLE coupons ADD COLUMN expires_at TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE coupons ADD COLUMN max_uses INTEGER")
        except Exception:
            pass
        # Image URL for command templates (optional image sent with the
        # command's response — trial_ready, welcome messages, etc.)
        try:
            await db.execute("ALTER TABLE command_templates ADD COLUMN image_url TEXT")
        except Exception:
            pass
        # Track whether the customer's whatsapp field was set MANUALLY by the
        # admin (via the Customers page). When set to 1, painel refreshes
        # MUST NOT overwrite it — the admin knows better than painel's data.
        try:
            await db.execute("ALTER TABLE customers ADD COLUMN whatsapp_locked INTEGER DEFAULT 0")
        except Exception:
            pass
        # Dedup log: records every time a duplicate delivery was blocked
        # by the delivery_queue. Lets the admin see the anti-dupe system
        # working in the notifications page.
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_dedup_log (
                    id TEXT PRIMARY KEY,
                    event_key TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    body TEXT NOT NULL,
                    image_url TEXT,
                    customer_id TEXT,
                    reason TEXT NOT NULL,          -- 'phone_event' | 'body_hash'
                    matched_delivery_id TEXT,      -- id of the delivery it collided with
                    matched_event_key TEXT,        -- the ORIGINAL event key if diff
                    window_minutes INTEGER NOT NULL,
                    blocked_at TEXT NOT NULL
                );
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_dedup_log_time ON notification_dedup_log(blocked_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_dedup_log_phone ON notification_dedup_log(phone, blocked_at DESC)"
            )
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


def get_setting_sync(key: str, default: str = "") -> str:
    """Synchronous version of get_setting for use in sync code paths
    (like phone normalization helpers called from data models).
    Uses the raw sqlite3 driver — no async needed."""
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else default
    except Exception:
        return default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()
    # Mirror to Mongo Atlas so multiple instances of WhatsFlow (dev/prod,
    # or main Pi + backup) see the same configuration. Best-effort — never
    # blocks the local write on Atlas being reachable.
    try:
        from services import mongo_store, config_sync
        await mongo_store.upsert_setting(key, value)
        await config_sync.save_setting(key, value)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("mongo_store.upsert_setting failed (non-fatal)")


async def get_all_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {row["key"]: row["value"] for row in rows}
