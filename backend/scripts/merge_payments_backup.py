"""Merge payments from an old whatsflow.db backup into the current DB.

Usage (Raspberry):  cd ~/WhatsFlow/backend && .venv/bin/python scripts/merge_payments_backup.py /tmp/whatsflow-backup-XXXX/whatsflow.db
"""
import sqlite3
import sys
from pathlib import Path

src = sys.argv[1] if len(sys.argv) > 1 else ""
if not Path(src).is_file():
    sys.exit("Informe o caminho do backup: merge_payments_backup.py /tmp/whatsflow-backup-XXXX/whatsflow.db")

dst = sqlite3.connect(Path(__file__).resolve().parent.parent / "whatsflow.db")
dst.execute("ATTACH DATABASE ? AS old", (src,))
cols = [r[1] for r in dst.execute("PRAGMA old.table_info(payments)")]
common = [c for c in cols if c in {r[1] for r in dst.execute("PRAGMA main.table_info(payments)")}]
before = dst.execute("SELECT COUNT(*) FROM main.payments").fetchone()[0]
col_list = ", ".join(common)
dst.execute(f"INSERT OR REPLACE INTO main.payments ({col_list}) SELECT {col_list} FROM old.payments")
dst.commit()
after = dst.execute("SELECT COUNT(*) FROM main.payments").fetchone()[0]
print(f"Pagamentos: {before} -> {after} (backup tinha {dst.execute('SELECT COUNT(*) FROM old.payments').fetchone()[0]})")
