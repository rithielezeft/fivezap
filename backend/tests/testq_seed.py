# Helper: seed/cleanup fake TESTQ_ rows in the REAL whatsflow.db (never sendable: next_retry_at/send_at = now+2h, fake phones)
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DB = os.path.join(os.path.dirname(__file__), "..", "whatsflow.db")


def seed():
    now = datetime.now(timezone.utc)
    later = (now + timedelta(hours=2)).isoformat()
    c = sqlite3.connect(DB, timeout=10)
    for i in range(1, 4):
        c.execute(
            "INSERT OR REPLACE INTO notification_deliveries (id, event_key, phone, body, image_url, customer_id, status, "
            "attempts, max_attempts, next_retry_at, last_error, body_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"TESTQ_d{i}", "expiration_3d", f"55000000000{i}", f"TESTQ body {i} Olá cliente", None, "227427597",
             "pending", 1, 5, later, "TESTQ fake error", f"TESTQ_hash{i}", (now - timedelta(minutes=10 - i)).isoformat()),
        )
    for i in range(4, 6):
        c.execute(
            "INSERT OR REPLACE INTO scheduled_reminders (id, event_key, phone, context, send_at, sent, created_at) "
            "VALUES (?,?,?,?,?,0,?)",
            (f"TESTQ_r{i}", "trial_1h_reminder", f"55000000000{i}",
             json.dumps({"name": f"TESTQ Nome {i}", "user": f"testq_user{i}"}), later, now.isoformat()),
        )
    c.commit()
    c.close()


def cleanup():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("DELETE FROM notification_deliveries WHERE id LIKE 'TESTQ_%'")
    c.execute("DELETE FROM scheduled_reminders WHERE id LIKE 'TESTQ_%'")
    c.commit()
    c.close()


def status():
    c = sqlite3.connect(DB, timeout=10)
    d = c.execute("SELECT id,status FROM notification_deliveries WHERE id LIKE 'TESTQ_%' ORDER BY id").fetchall()
    r = c.execute("SELECT id,sent FROM scheduled_reminders WHERE id LIKE 'TESTQ_%' ORDER BY id").fetchall()
    other = c.execute("SELECT COUNT(*) FROM notification_deliveries WHERE id NOT LIKE 'TESTQ_%' AND status IN ('pending','sending')").fetchone()[0]
    other_r = c.execute("SELECT COUNT(*) FROM scheduled_reminders WHERE id NOT LIKE 'TESTQ_%' AND sent=0").fetchone()[0]
    c.close()
    return d, r, other, other_r


if __name__ == "__main__":
    {"seed": seed, "cleanup": cleanup}.get(sys.argv[1], lambda: None)()
    print(status())
