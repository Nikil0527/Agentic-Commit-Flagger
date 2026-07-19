import json

import pytest
from fastapi.testclient import TestClient

from agent.main import create_app


class FakeGitHub:
    def __init__(self):
        self.repo = "me/repo"
        self.calls = 0

    async def recent_commits(self, limit=20):
        self.calls += 1
        return [{"sha": "abc123", "message": "some commit", "author": "me", "date": "2026-07-13T00:00:00Z"}]

    async def commit_diff(self, sha, max_chars=4000):
        return "+ a diff line"


class FakeRanker:
    async def rank(self, alert, commits, diffs):
        return {
            "suspects": [{"sha": commits[0]["sha"], "confidence": "high", "reasoning": "test"}],
            "assessment": "test assessment",
            "model": "fake",
        }


class FakeImpact:
    async def estimate(self, alert):
        return {"description": "~12% of requests failing", "job": alert.get("labels", {}).get("job", "")}


def make_pm(tmp_path):
    from agent.postmortem import PostmortemWriter

    pm = PostmortemWriter(model="test", out_dir=tmp_path / "postmortems")
    pm.enabled = False
    return pm


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
    return TestClient(create_app(
        data_dir=tmp_path, github=FakeGitHub(), ranker=None,
        impact=FakeImpact(), postmortems=make_pm(tmp_path),
    ))


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

    # a duplicate of the first resolve arrives late and must not close the new incident
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


def test_new_incident_fetches_commits(tmp_path):
    gh = FakeGitHub()
    client = TestClient(create_app(data_dir=tmp_path, github=gh, ranker=None))

    client.post("/webhook/alertmanager", json=firing_payload())
    assert gh.calls == 1

    events = [json.loads(l) for l in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    fetched = [e for e in events if e["event"] == "commits_fetched"]
    assert len(fetched) == 1
    assert fetched[0]["data"]["commits"][0]["sha"] == "abc123"
    assert any(e["event"] == "ranking_skipped" for e in events)

    # refire must not refetch
    client.post("/webhook/alertmanager", json=firing_payload())
    assert gh.calls == 1


def test_new_incident_ranks_culprits(tmp_path):
    client = TestClient(create_app(
        data_dir=tmp_path, github=FakeGitHub(), ranker=FakeRanker(),
        impact=FakeImpact(), postmortems=make_pm(tmp_path),
    ))
    client.post("/webhook/alertmanager", json=firing_payload())

    events = [json.loads(l) for l in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    ranked = [e for e in events if e["event"] == "culprits_ranked"]
    assert len(ranked) == 1
    assert ranked[0]["data"]["suspects"][0]["sha"] == "abc123"

    brief = next(e for e in events if e["event"] == "brief_posted")
    assert "impact: ~12% of requests failing" in brief["data"]["text"]
    assert any(e["event"] == "impact_estimated" for e in events)


def test_resolve_writes_postmortem(tmp_path):
    client = TestClient(create_app(
        data_dir=tmp_path, github=FakeGitHub(), ranker=FakeRanker(),
        impact=FakeImpact(), postmortems=make_pm(tmp_path),
    ))
    incident_id = client.post("/webhook/alertmanager", json=firing_payload()).json()["incident"]

    r = client.post(f"/incidents/{incident_id}/resolve")
    assert r.status_code == 200
    assert r.json()["closed_now"] is True

    pm_file = tmp_path / "postmortems" / f"{incident_id}.md"
    assert pm_file.exists()
    text = pm_file.read_text(encoding="utf-8")
    assert "## timeline" in text and "abc123" in text

    incidents = client.get("/incidents").json()
    assert incidents[0]["status"] == "resolved"


def test_resolve_unknown_incident_404(client):
    assert client.post("/incidents/inc-nope/resolve").status_code == 404


def test_resolve_rejects_path_traversal(client):
    assert client.post("/incidents/..%2F..%2Fsecrets/resolve").status_code == 404


def test_resolve_twice_does_not_rerun(tmp_path):
    client = TestClient(create_app(
        data_dir=tmp_path, github=FakeGitHub(), ranker=FakeRanker(),
        impact=FakeImpact(), postmortems=make_pm(tmp_path),
    ))
    incident_id = client.post("/webhook/alertmanager", json=firing_payload()).json()["incident"]

    first = client.post(f"/incidents/{incident_id}/resolve").json()
    second = client.post(f"/incidents/{incident_id}/resolve").json()
    assert first["closed_now"] is True
    assert second["closed_now"] is False

    events = [json.loads(l) for l in (tmp_path / f"{incident_id}.jsonl").read_text().splitlines()]
    written = [e for e in events if e["event"] == "postmortem_written"]
    assert len(written) == 1


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
