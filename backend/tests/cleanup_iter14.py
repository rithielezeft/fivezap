# Cleanup helper for iter14: removes customer_prefs for joaonew* test logins and TEST_/temp payments check
import os, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from pymongo import MongoClient
from services.mongo_store import _clean_url
url = _clean_url(os.environ.get("WHATSFLOW_MONGO_URL")) or os.environ.get("MONGO_URL")
dbn = (os.environ.get("WHATSFLOW_DB_NAME") if os.environ.get("WHATSFLOW_MONGO_URL") else None) or os.environ.get("DB_NAME")
db = MongoClient(url, serverSelectionTimeoutMS=8000)[dbn]
ids = ["227470206", "227470351", "227470352"]
print("deleted prefs:", db.customer_prefs.delete_many({"_id": {"$in": ids}}).deleted_count)
print("remaining prefs:", db.customer_prefs.count_documents({"_id": {"$in": ids}}))
print("mongo pending test-customer payments last hour:", db.payments.count_documents({"customer_id": {"$in": ids}, "status": "pending"}))
