import math
import os
from datetime import datetime, timezone

import httpx

DEFAULT_PROM_URL = "http://localhost:9090"


class ImpactEstimator:
    """Reads prometheus at diagnosis time so the brief can say how much traffic is hurting."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        base = os.environ.get("PROMETHEUS_URL", DEFAULT_PROM_URL)
        self.http = client or httpx.AsyncClient(base_url=base, timeout=10)

    async def estimate(self, alert: dict) -> dict | None:
        labels = alert.get("labels", {})
        job = labels.get("job", "")
        service = labels.get("service_name", "")
        failure_class = labels.get("failure_class", "")
        try:
            if failure_class == "error-spike" and job:
                ratio = await self._query(
                    f'sum(rate(rpc_server_duration_milliseconds_count{{rpc_grpc_status_code!="0",job="{job}"}}[5m]))'
                    f' / sum(rate(rpc_server_duration_milliseconds_count{{job="{job}"}}[5m]))'
                )
                if ratio is None:
                    return None
                desc = f"~{ratio * 100:.0f}% of requests to {job} failing"
                total = await self._query(f'sum(rate(rpc_server_duration_milliseconds_count{{job="{job}"}}[5m]))')
                if total:
                    desc += f" at {total:.1f} req/s"
            elif failure_class == "latency" and service:
                p99 = await self._query(
                    'histogram_quantile(0.99, sum by (le) (rate('
                    f'traces_span_metrics_duration_milliseconds_bucket{{span_kind="SPAN_KIND_SERVER",service_name="{service}"}}[5m])))'
                )
                if p99 is None:
                    return None
                desc = f"p99 latency for {service} at {p99 / 1000:.1f}s"
            else:
                return None

            minutes = self._minutes_since(alert.get("starts_at", ""))
            if minutes:
                desc += f" for {minutes} min"
            return {"description": desc, "job": job or service}
        except Exception:
            # impact is garnish so never let it break the investigation
            return None

    async def _query(self, promql: str) -> float | None:
        r = await self.http.get("/api/v1/query", params={"query": promql})
        r.raise_for_status()
        result = r.json().get("data", {}).get("result", [])
        if not result:
            return None
        value = float(result[0]["value"][1])
        return None if math.isnan(value) else value

    def _minutes_since(self, iso: str) -> int:
        if not iso:
            return 0
        try:
            start = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            return max(int((datetime.now(timezone.utc) - start).total_seconds() // 60), 0)
        except Exception:
            return 0
