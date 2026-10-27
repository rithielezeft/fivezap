# API tests for Fila de envio: GET /api/queue + POST /api/queue/cancel (uses fake TESTQ_ rows in real DB; cleaned up)
import os
import sqlite3
import sys
from datetime import datetime, timezone

import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
import testq_seed as seed  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": "Rithi0518@"})
    if r.status_code != 200:
        pytest.skip("login failed")
    d = r.json()
    s.headers["Authorization"] = f"Bearer {d.get('token') or d.get('access_token')}"
    return s


@pytest.fixture
def seeded():
    seed.cleanup()
    seed.seed()
    # an already-sent row that must never be touched
    c = sqlite3.connect(seed.DB, timeout=10)
    c.execute(
        "INSERT INTO notification_deliveries (id,event_key,phone,body,status,attempts,max_attempts,sent_at,created_at) "
        "VALUES ('TESTQ_sent','expiration_1d','550000000009','TESTQ sent body','sent',1,5,?,?)",
        (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    c.commit(); c.close()
    yield
    seed.cleanup()


class TestQueueApi:
    def test_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/queue").status_code == 401
        assert requests.post(f"{BASE_URL}/api/queue/cancel", json={"all": True}).status_code == 401

    def test_get_queue_structure(self, client, seeded):
        r = client.get(f"{BASE_URL}/api/queue")
        assert r.status_code == 200
        d = r.json()
        for k in ("run", "deliveries", "reminders", "history", "stats"):
            assert k in d
        assert "running" in d["run"] and isinstance(d["run"]["items"], list)
        dels = [x for x in d["deliveries"] if x["id"].startswith("TESTQ_")]
        rems = [x for x in d["reminders"] if x["id"].startswith("TESTQ_")]
        assert len(dels) == 3 and len(rems) == 2
        assert all(x["kind"] == "delivery" and x["status"] == "pending" for x in dels)
        assert dels[0]["title"] and dels[0]["last_error"] == "TESTQ fake error"
        r4 = [x for x in rems if x["id"] == "TESTQ_r4"][0]
        assert r4["kind"] == "reminder" and r4["status"] == "scheduled"
        assert r4["name"] == "TESTQ Nome 4" and r4["login"] == "testq_user4"
        # fake ctx only has name/user, so other placeholders stay literal; check rendered vars
        assert r4["body"] and "TESTQ Nome 4" in r4["body"] and "{name}" not in r4["body"] and "testq_user4" in r4["body"]
        assert r4["eta"]
        st = d["stats"]
        assert st["in_queue"] >= 3 and st["scheduled_reminders"] >= 2 and st["retrying"] >= 3
        assert st["total_pending"] == st["waiting_run"] + st["in_queue"] + st["scheduled_reminders"]
        assert any(h["id"] == "TESTQ_sent" for h in d["history"])
        assert not any(h["id"].startswith("TESTQ_d") for h in d["history"])

    def test_cancel_selected_only(self, client, seeded):
        r = client.post(f"{BASE_URL}/api/queue/cancel", json={"items": [
            {"kind": "delivery", "id": "TESTQ_d1"}, {"kind": "reminder", "id": "TESTQ_r4"},
            {"kind": "delivery", "id": "TESTQ_sent"},  # already sent → untouched
        ]})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["cancelled"]["delivery"] == 1 and j["cancelled"]["reminder"] == 1 and j["total"] == 2
        dels, rems, _, _ = seed.status()
        dd, rr = dict(dels), dict(rems)
        assert dd["TESTQ_d1"] == "cancelled" and dd["TESTQ_d2"] == "pending" and dd["TESTQ_d3"] == "pending"
        assert dd["TESTQ_sent"] == "sent"
        assert rr["TESTQ_r4"] == 3 and rr["TESTQ_r5"] == 0
        g = client.get(f"{BASE_URL}/api/queue").json()
        ids = {x["id"] for x in g["deliveries"]} | {x["id"] for x in g["reminders"]}
        assert "TESTQ_d1" not in ids and "TESTQ_r4" not in ids and "TESTQ_d2" in ids
        h = [x for x in g["history"] if x["id"] == "TESTQ_d1"][0]
        assert h["status"] == "cancelled"
        # cancelling again is a no-op
        assert client.post(f"{BASE_URL}/api/queue/cancel", json={"items": [{"kind": "delivery", "id": "TESTQ_d1"}]}).json()["total"] == 0

    def test_cancel_all(self, client, seeded):
        _, _, other, other_r = seed.status()
        if other or other_r:
            pytest.skip("real pending items present — refusing to cancel all")
        r = client.post(f"{BASE_URL}/api/queue/cancel", json={"all": True})
        assert r.status_code == 200
        j = r.json()
        assert j["cancelled"]["delivery"] == 3 and j["cancelled"]["reminder"] == 2
        dels, rems, _, _ = seed.status()
        dd = dict(dels)
        assert dd["TESTQ_sent"] == "sent"
        assert all(v == "cancelled" for k, v in dd.items() if k != "TESTQ_sent")
        assert all(v == 3 for _, v in rems)
        g = client.get(f"{BASE_URL}/api/queue").json()
        assert g["stats"]["total_pending"] == 0

    def test_cancel_invalid_payload(self, client):
        r = client.post(f"{BASE_URL}/api/queue/cancel", json={"items": [{"kind": "delivery"}]})
        assert r.status_code == 422
        r = client.post(f"{BASE_URL}/api/queue/cancel", json={})
        assert r.status_code == 200 and r.json()["total"] == 0
