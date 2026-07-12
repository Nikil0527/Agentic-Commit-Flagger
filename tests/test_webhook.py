import pytest
from fastapi.testclient import TestClient

from agent.main import create_app


def firing_payload(group_key="{}:{alertname='GrpcHighErrorRate'}", status="firing", starts_at="2026-07-11T12:00:00Z"):
    return {
        "version": "4",
        "groupKey": group_key,
        "status": status,
        "receiver": "agent",
        "groupLabels": {"alertname": "GrpcHighErrorRate", "job": "otel-demo/product-catalog"},
        "commonLabels": {
            "alertname": "GrpcHighErrorRate",
            "job": "otel-demo/product-catalog",
            "severity": "critical",
            "failure_class": "error-spike",
        },
        "commonAnnotations": {"summary": "otel-demo/product-catalog grpc error rate above 5%"},
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": status,
                "labels": {"alertname": "GrpcHighErrorRate", "job": "otel-demo/product-catalog"},
                "annotations": {},
                "startsAt": starts_at,
                "fingerprint": "abc123",
            }
        ],
    }


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(data_dir=tmp_path))


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_firing_creates_incident(client):
    r = client.post("/webhook/alertmanager", json=firing_payload())
    assert r.status_code == 200
    assert r.json()["incident"].startswith("inc-")

    incidents = client.get("/incidents").json()
    assert len(incidents) == 1
    assert incidents[0]["status"] == "open"
    assert incidents[0]["alertname"] == "GrpcHighErrorRate"


def test_repeat_firing_is_same_incident(client):
    first = client.post("/webhook/alertmanager", json=firing_payload()).json()["incident"]
    second = client.post("/webhook/alertmanager", json=firing_payload()).json()["incident"]
    assert first == second
    assert len(client.get("/incidents").json()) == 1


def test_resolved_closes_incident(client):
    client.post("/webhook/alertmanager", json=firing_payload())
    r = client.post("/webhook/alertmanager", json=firing_payload(status="resolved"))
    assert r.status_code == 200

    incidents = client.get("/incidents").json()
    assert incidents[0]["status"] == "resolved"


def test_resolved_without_incident_is_noop(client):
    r = client.post("/webhook/alertmanager", json=firing_payload(status="resolved"))
    assert r.json()["incident"] is None
    assert client.get("/incidents").json() == []


def test_different_groups_are_separate_incidents(client):
    a = client.post("/webhook/alertmanager", json=firing_payload(group_key="g1")).json()["incident"]
    b = client.post("/webhook/alertmanager", json=firing_payload(group_key="g2")).json()["incident"]
    assert a != b
    assert len(client.get("/incidents").json()) == 2


def test_malformed_payload_rejected(client):
    assert client.post("/webhook/alertmanager", json={"nope": True}).status_code == 422


def test_refire_then_resolve_after_reopen(client):
    client.post("/webhook/alertmanager", json=firing_payload(starts_at="2026-07-11T12:00:00Z"))
    client.post("/webhook/alertmanager", json=firing_payload(status="resolved", starts_at="2026-07-11T12:00:00Z"))
    reopened = client.post("/webhook/alertmanager", json=firing_payload(starts_at="2026-07-11T13:00:00Z")).json()["incident"]

    incidents = {i["id"]: i for i in client.get("/incidents").json()}
    assert incidents[reopened]["status"] == "open"
    assert len(incidents) == 2


def test_stale_resolved_does_not_close_reopened_incident(client):
    client.post("/webhook/alertmanager", json=firing_payload(starts_at="2026-07-11T12:00:00Z"))
    client.post("/webhook/alertmanager", json=firing_payload(status="resolved", starts_at="2026-07-11T12:00:00Z"))
    reopened = client.post("/webhook/alertmanager", json=firing_payload(starts_at="2026-07-11T13:00:00Z")).json()["incident"]

    # duplicate of the first resolve arrives late - must not close the new incident
    r = client.post("/webhook/alertmanager", json=firing_payload(status="resolved", starts_at="2026-07-11T12:00:00Z"))
    assert r.json()["incident"] is None

    incidents = {i["id"]: i for i in client.get("/incidents").json()}
    assert incidents[reopened]["status"] == "open"


def test_store_survives_restart(client, tmp_path):
    from agent.main import create_app
    from fastapi.testclient import TestClient as TC

    client.post("/webhook/alertmanager", json=firing_payload())
    restarted = TC(create_app(data_dir=tmp_path))
    same = restarted.post("/webhook/alertmanager", json=firing_payload()).json()["incident"]

    incidents = restarted.get("/incidents").json()
    assert len(incidents) == 1
    assert incidents[0]["id"] == same


def test_corrupt_log_line_is_skipped(client, tmp_path):
    from agent.main import create_app
    from fastapi.testclient import TestClient as TC

    client.post("/webhook/alertmanager", json=firing_payload())
    jsonl = next(tmp_path.glob("*.jsonl"))
    with jsonl.open("a", encoding="utf-8") as f:
        f.write('{"ts": "2026-07-12T0')

    restarted = TC(create_app(data_dir=tmp_path))
    incidents = restarted.get("/incidents").json()
    assert len(incidents) == 1
    assert incidents[0]["status"] == "open"
