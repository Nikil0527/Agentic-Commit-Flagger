import httpx
import pytest

from agent.impact import ImpactEstimator


def prom_client(values):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        value = values.pop(0) if values else None
        result = [] if value is None else [{"metric": {}, "value": [1700000000, str(value)]}]
        return httpx.Response(200, json={"status": "success", "data": {"result": result}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://prom.test")


ERROR_ALERT = {
    "alertname": "GrpcHighErrorRate",
    "labels": {"job": "otel-demo/product-catalog", "failure_class": "error-spike"},
    "annotations": {},
    "starts_at": "2026-07-17T00:00:00+00:00",
}


@pytest.mark.anyio
async def test_error_spike_impact():
    est = ImpactEstimator(client=prom_client([0.12, 1.5]))
    out = await est.estimate(ERROR_ALERT)
    assert "12% of requests" in out["description"]
    assert "1.5 req/s" in out["description"]
    assert "min" in out["description"]


@pytest.mark.anyio
async def test_latency_impact():
    alert = {"alertname": "HighP99Latency", "labels": {"job": "otel-demo/flagd", "failure_class": "latency"}, "annotations": {}}
    est = ImpactEstimator(client=prom_client([4.9]))
    out = await est.estimate(alert)
    assert "p99 latency" in out["description"]
    assert "4.9s" in out["description"]


@pytest.mark.anyio
async def test_no_data_returns_none():
    est = ImpactEstimator(client=prom_client([None]))
    assert await est.estimate(ERROR_ALERT) is None


@pytest.mark.anyio
async def test_unreachable_prometheus_returns_none():
    def handler(request):
        raise httpx.ConnectError("nope")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://prom.test")
    est = ImpactEstimator(client=client)
    assert await est.estimate(ERROR_ALERT) is None


@pytest.mark.anyio
async def test_unknown_failure_class_returns_none():
    alert = {"alertname": "PodCrashLooping", "labels": {"failure_class": "crash-loop"}, "annotations": {}}
    est = ImpactEstimator(client=prom_client([1.0]))
    assert await est.estimate(alert) is None
