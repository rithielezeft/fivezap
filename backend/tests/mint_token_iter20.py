# Mint a short-lived admin token for tests (preview has legacy password login disabled)
import os, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from services.auth import create_token
print(create_token("admin", days=1))
