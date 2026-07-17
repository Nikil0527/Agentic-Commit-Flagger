from agent.brief import build_brief

ALERT = {
    "alertname": "GrpcHighErrorRate",
    "labels": {"job": "otel-demo/product-catalog"},
    "annotations": {"summary": "otel-demo/product-catalog grpc error rate above 5%"},
}

RANKING = {
    "suspects": [
        {"sha": "aaa111", "confidence": "high", "reasoning": "flag flipped to on"},
        {"sha": "bbb222", "confidence": "low", "reasoning": "touched the same service"},
    ],
    "assessment": "a config change enabled a failure flag",
}


def test_brief_contains_the_story():
    text = build_brief(ALERT, RANKING, "me/repo")
    assert "GrpcHighErrorRate" in text
    assert "otel-demo/product-catalog" in text
    assert "aaa111" in text and "high" in text
    assert "flag flipped to on" in text
    assert "https://github.com/me/repo/commit/aaa111" in text
    assert "config change enabled a failure flag" in text


def test_brief_with_no_suspects():
    text = build_brief(ALERT, {"suspects": [], "assessment": ""}, "me/repo")
    assert "no commit stands out" in text
    assert "github.com" not in text
