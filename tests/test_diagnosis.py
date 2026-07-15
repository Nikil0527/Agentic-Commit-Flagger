import json

import httpx
import pytest

from agent.diagnosis import CulpritRanker

ALERT = {"alertname": "GrpcHighErrorRate", "labels": {"job": "otel-demo/product-catalog"}, "annotations": {}}
COMMITS = [
    {"sha": "aaa111", "message": "enable failure flag", "author": "me", "date": "2026-07-13"},
    {"sha": "bbb222", "message": "update readme", "author": "me", "date": "2026-07-12"},
]
DIFFS = {"aaa111": '+ "defaultVariant": "on"', "bbb222": "+ words"}

GOOD_RESPONSE = json.dumps({
    "suspects": [{"sha": "aaa111", "confidence": "high", "reasoning": "flag flipped to on"}],
    "assessment": "config change enabled a failure flag",
})


def fake_llm(response_text, capture=None):
    def handler(request):
        if capture is not None:
            capture.append(json.loads(request.content))
        body = {"choices": [{"message": {"role": "assistant", "content": response_text}}]}
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://fake-llm.test")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_rank_parses_suspects():
    ranker = CulpritRanker(client=fake_llm(GOOD_RESPONSE), model="test-model")
    result = await ranker.rank(ALERT, COMMITS, DIFFS)
    assert result["suspects"][0]["sha"] == "aaa111"
    assert result["model"] == "test-model"


@pytest.mark.anyio
async def test_prompt_contains_alert_commits_and_diffs():
    captured = []
    ranker = CulpritRanker(client=fake_llm(GOOD_RESPONSE, capture=captured), model="test-model")
    await ranker.rank(ALERT, COMMITS, DIFFS)

    prompt = captured[0]["messages"][1]["content"]
    assert "GrpcHighErrorRate" in prompt
    assert "enable failure flag" in prompt
    assert "defaultVariant" in prompt
    assert captured[0]["model"] == "test-model"


@pytest.mark.anyio
async def test_code_fenced_json_still_parses():
    fenced = f"```json\n{GOOD_RESPONSE}\n```"
    ranker = CulpritRanker(client=fake_llm(fenced), model="test-model")
    result = await ranker.rank(ALERT, COMMITS, DIFFS)
    assert result["suspects"][0]["sha"] == "aaa111"


@pytest.mark.anyio
async def test_garbage_response_is_captured_not_crashed():
    ranker = CulpritRanker(client=fake_llm("the culprit is probably aaa111"), model="test-model")
    result = await ranker.rank(ALERT, COMMITS, DIFFS)
    assert result["suspects"] == []
    assert result["parse_error"] is True
    assert "aaa111" in result["raw"]


@pytest.mark.anyio
async def test_llm_error_raises():
    def handler(request):
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://fake-llm.test")
    ranker = CulpritRanker(client=client, model="test-model")
    with pytest.raises(httpx.HTTPStatusError):
        await ranker.rank(ALERT, COMMITS, DIFFS)
