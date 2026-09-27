"""End-to-end smoke tests — run offline with no services.

    cd backend && .venv/bin/python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture()
def client(isolated_env):
    from fastapi.testclient import TestClient

    from synapseos.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _seed_kb(client):
    client.post("/api/v1/documents", json={
        "title": "Orbits",
        "text": "A low earth orbit satellite circles the planet every ninety minutes. "
                "Low earth orbit altitudes range from two hundred to two thousand kilometers. "
                "Starlink operates in low earth orbit."})


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_chat_feedback_learning_loop(client):
    _seed_kb(client)
    r = client.post("/api/v1/chat", json={"user_id": "t", "text": "what is a low earth orbit?"})
    assert r.status_code == 200
    d = r.json()
    assert "low earth orbit" in d["answer"].lower()
    assert d["confidence"] > 0
    assert d["explanation"]["sources"], "answer must cite sources"
    assert any(s["step"] == "self_evaluation" for s in d["explanation"]["trace"])

    # feedback → reward + policy update
    r = client.post("/api/v1/chat/feedback",
                    json={"interaction_id": d["interaction_id"], "kind": "thumb", "value": "up"})
    assert r.status_code == 200
    assert r.json()["reward"] == 1.0
    assert r.json()["policy"]["feedback_count"] >= 1

    # correction → memory + proposed fact
    r = client.post("/api/v1/chat/feedback",
                    json={"interaction_id": d["interaction_id"], "kind": "correction",
                          "text": "Low earth orbit starts at 160 km, not 200 km"})
    assert r.json()["proposed_fact_id"] is not None
    fact_id = r.json()["proposed_fact_id"]

    # fact pending until approved
    facts = client.get("/api/v1/kb/facts?status=pending").json()
    assert any(f["id"] == fact_id for f in facts)
    active = client.get("/api/v1/kb/facts?status=active").json()
    assert all(f["id"] != fact_id for f in active)

    # approve → live
    r = client.post(f"/api/v1/kb/facts/{fact_id}/approve")
    assert r.json()["status"] == "active"

    # next answer uses the learned fact + exemplar memory
    r = client.post("/api/v1/chat", json={"user_id": "t", "text": "where does low earth orbit start?"})
    assert "160" in r.json()["answer"]

    # rollback removes it again
    v = client.get("/api/v1/kb/versions").json()
    target = [x for x in v if x["facts"] == 0][-1]
    r = client.post(f"/api/v1/kb/versions/{target['id']}/rollback")
    assert r.status_code == 200
    facts = client.get("/api/v1/kb/facts?status=retired").json()
    assert any(f["id"] == fact_id for f in facts)


def test_low_confidence_flagging_and_review(client):
    r = client.post("/api/v1/chat", json={"user_id": "t", "text": "what is the airspeed of an unladen swallow in furlongs per fortnight?"})
    assert r.json()["flagged_for_review"] is True
    queue = client.get("/api/v1/admin/review?kind=low_confidence").json()
    assert len(queue) >= 1
    item = queue[0]
    r = client.post(f"/api/v1/admin/review/{item['id']}/resolve", json={"decision": "resolved"})
    assert r.json()["status"] == "resolved"


def test_multimodal_image(client):
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (10, 200, 90)).save(buf, "PNG")
    r = client.post("/api/v1/chat", json={
        "user_id": "t", "text": "look at this green diagram",
        "attachments": [{"kind": "image", "filename": "g.png", "caption": "green diagram",
                         "data_base64": base64.b64encode(buf.getvalue()).decode()}]})
    assert r.status_code == 200
    assert r.json()["modality"] == "multimodal"
    assert r.json()["attachments"][0]["dominant_colors"]


def test_personalization_per_user(client):
    _seed_kb(client)
    for user in ("u1", "u2"):
        client.post("/api/v1/chat", json={"user_id": user, "text": "what is a low earth orbit?"})
    iid = client.post("/api/v1/chat", json={"user_id": "u1", "text": "tell me about orbits again"}).json()["interaction_id"]
    client.post("/api/v1/chat/feedback",
                json={"interaction_id": iid, "kind": "text", "text": "good but shorter please"})
    p1 = client.get("/api/v1/users/u1/profile").json()
    p2 = client.get("/api/v1/users/u2/profile").json()
    assert p1["profile"]["feedback_count"] == 1
    assert p2["profile"]["feedback_count"] == 0
    assert p1["profile"]["verbosity_pref"] < 1.0


def test_drift_detection(client):
    _seed_kb(client)
    for i in range(50):
        client.post("/api/v1/chat", json={"user_id": "t", "text": f"question number {i} about orbits and altitude"})
    r = client.post("/api/v1/admin/drift/recompute")
    assert r.status_code == 200
    assert "psi" in r.json()


def test_metrics_and_ledger(client):
    _seed_kb(client)
    client.post("/api/v1/chat", json={"user_id": "t", "text": "what is a low earth orbit?"})
    assert client.get("/api/v1/admin/metrics/learning-curve").json()["series"]
    assert client.get("/api/v1/admin/interactions").json()
    ov = client.get("/api/v1/admin/overview").json()
    assert ov["totals"]["interactions"] >= 1
    assert ov["totals"]["documents"] == 1


def test_rate_limiting(client):
    codes = [client.get("/api/v1/health").status_code for _ in range(400)]
    assert 429 in codes, "rate limiter must engage under burst"


def test_auth_enforced_when_configured(isolated_env):
    isolated_env["SYNAPSE_API_KEYS"] = "k1"
    isolated_env["SYNAPSE_ADMIN_KEY"] = "admin1"
    from fastapi.testclient import TestClient

    from synapseos.main import create_app

    with TestClient(create_app()) as c:
        # no credentials -> rejected (401 from the API-key guard)
        assert c.get("/api/v1/admin/overview").status_code in (401, 403)
        assert c.get("/api/v1/documents").status_code == 401
        # valid API key -> user endpoints OK, admin still denied
        assert c.get("/api/v1/documents", headers={"X-API-Key": "k1"}).status_code == 200
        assert c.get("/api/v1/admin/overview", headers={"X-API-Key": "k1"}).status_code == 403
        # admin key -> full access
        assert c.get("/api/v1/admin/overview", headers={"X-API-Key": "admin1"}).status_code == 200


def test_security_audit_battery(tmp_path):
    from synapseos.security.audit import run_audit

    # audit a client-less app instance is not possible; run against test server
    os.environ["SYNAPSE_DATA_DIR"] = str(tmp_path / "audit")
    os.environ["SYNAPSE_DB_URL"] = f"sqlite:///{tmp_path}/audit/t.db"
    from fastapi.testclient import TestClient

    import importlib

    import synapseos.core.config as cfg
    importlib.reload(cfg)
    import synapseos.main as main
    importlib.reload(main)

    import threading
    import uvicorn

    config = uvicorn.Config(main.create_app(), host="127.0.0.1", port=8901, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    import time

    for _ in range(50):
        try:
            import httpx

            httpx.get("http://127.0.0.1:8901/api/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    report = run_audit("http://127.0.0.1:8901", out_path=str(tmp_path / "audit.json"))
    assert len(report.findings) >= 10
    assert any(f.check_id == "auth-mode" and f.status == "FAIL" for f in report.findings)
    assert any(f.check_id == "rate-limit" and f.status == "PASS" for f in report.findings)
    server.should_exit = True
