# Verify a venv with ONLY requirements-pi.txt can import deps + mirror/auth modules
import importlib, sys
ok = True
for m in ["asyncpg", "fastapi", "motor", "httpx", "aiosqlite", "services.supabase_mirror", "routers.supabase_auth"]:
    try:
        mod = importlib.import_module(m)
        print("OK", m, getattr(mod, "__version__", ""))
    except Exception as e:
        ok = False
        print("FAIL", m, type(e).__name__, e)
print("PY", sys.executable)
sys.exit(0 if ok else 1)
