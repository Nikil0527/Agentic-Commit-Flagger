import json
import os
from pathlib import Path

import httpx

from agent.diagnosis import DEFAULT_BASE_URL, DEFAULT_MODEL

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "postmortems"

SYSTEM = """You are an SRE writing a short blameless postmortem from an incident event log.
The log records every step an incident response agent took. Write these markdown sections and nothing else:
## summary
two or three sentences on what happened and how it was found
## root cause
name the culprit commit and mechanism if the log identifies one
## action items
three to five concrete checkbox items like - [ ] item, aimed at prevention not blame"""


class PostmortemWriter:
    """Drafts a postmortem from the incident event log, falls back to a plain timeline without an llm."""

    def __init__(self, client: httpx.AsyncClient | None = None, model: str | None = None, out_dir: Path | None = None):
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.out_dir = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
        key = os.environ.get("LLM_API_KEY", "")
        self.enabled = client is not None or bool(key)
        if client is not None:
            self.http = client
        else:
            base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
            self.http = httpx.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {key}"}, timeout=60)

    async def write(self, incident_id: str, events: list[dict]) -> Path:
        narrative = await self._narrative(events) if self.enabled else ""
        if not narrative:
            narrative = self._fallback_sections(events)

        md = "\n".join([
            f"# postmortem {incident_id}",
            "",
            narrative.strip(),
            "",
            "## timeline",
            self._timeline(events),
            "",
        ])
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{incident_id}.md"
        path.write_text(md, encoding="utf-8")
        return path

    async def _narrative(self, events: list[dict]) -> str:
        try:
            r = await self.http.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": json.dumps(events)[:30000]},
                    ],
                },
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.strip("`").removeprefix("markdown").strip()
            return text
        except Exception:
            return ""

    def _fallback_sections(self, events: list[dict]) -> str:
        first = events[0]["data"] if events else {}
        ranked = next((e["data"] for e in events if e.get("event") == "culprits_ranked"), {})
        suspects = ranked.get("suspects", [])
        root = f"suspect commit {suspects[0].get('sha', '?')}: {suspects[0].get('reasoning', '')}" if suspects else "not identified"
        return "\n".join([
            "## summary",
            f"alert {first.get('alertname', 'unknown')} fired and the agent investigated, see timeline",
            "## root cause",
            root,
            "## action items",
            "- [ ] fill in after review",
        ])

    def _timeline(self, events: list[dict]) -> str:
        lines = []
        for e in events:
            detail = ""
            data = e.get("data", {})
            if e.get("event") == "alert_received":
                detail = data.get("alertname", "")
            elif e.get("event") == "culprits_ranked":
                s = data.get("suspects", [])
                detail = f"top suspect {s[0].get('sha', '?')}" if s else "no suspects"
            elif e.get("event") == "runbook_matched":
                detail = data.get("runbook", "")
            elif e.get("event") == "impact_estimated":
                detail = data.get("description", "")
            elif e.get("event") == "resolved":
                detail = data.get("by", "alert cleared")
            lines.append(f"- {e.get('ts', '?')} {e.get('event', '?')} {detail}".rstrip())
        return "\n".join(lines)
