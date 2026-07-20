import httpx
import pytest

from agent.postmortem import PostmortemWriter

EVENTS = [
    {"ts": "2026-07-17T01:38:52+00:00", "event": "alert_received", "group_key": "g", "data": {"alertname": "GrpcHighErrorRate"}},
    {"ts": "2026-07-17T01:38:53+00:00", "event": "commits_fetched", "group_key": "g", "data": {"commits": []}},
    {"ts": "2026-07-17T01:38:55+00:00", "event": "culprits_ranked", "group_key": "g",
     "data": {"suspects": [{"sha": "aaa111", "confidence": "high", "reasoning": "flag flip"}], "assessment": "flag was enabled"}},
    {"ts": "2026-07-17T01:38:56+00:00", "event": "runbook_matched", "group_key": "g", "data": {"runbook": "error-rate-spike.md"}},
    {"ts": "2026-07-17T01:40:00+00:00", "event": "resolved", "group_key": "g", "data": {"by": "manual"}},
]


def llm_client(text):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://llm.test")


@pytest.mark.anyio
async def test_postmortem_with_llm(tmp_path):
    narrative = "## summary\nthe flag broke prod\n## root cause\ncommit aaa111\n## action items\n- [ ] guard flags"
    pm = PostmortemWriter(client=llm_client(narrative), model="test", out_dir=tmp_path)
    path = await pm.write("inc-test-1", EVENTS)

    text = path.read_text(encoding="utf-8")
    assert "# postmortem inc-test-1" in text
    assert "the flag broke prod" in text
    assert "## timeline" in text
    assert "top suspect aaa111" in text
    assert "resolved manual" in text


@pytest.mark.anyio
async def test_postmortem_fallback_without_llm(tmp_path):
    pm = PostmortemWriter(client=None, model="test", out_dir=tmp_path)
    pm.enabled = False
    path = await pm.write("inc-test-2", EVENTS)

    text = path.read_text(encoding="utf-8")
    assert "## summary" in text
    assert "aaa111" in text
    assert "## timeline" in text


@pytest.mark.anyio
async def test_llm_failure_falls_back(tmp_path):
    def handler(request):
        return httpx.Response(503, json={"error": "down"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://llm.test")
    pm = PostmortemWriter(client=client, model="test", out_dir=tmp_path)
    path = await pm.write("inc-test-3", EVENTS)
    assert "## summary" in path.read_text(encoding="utf-8")
