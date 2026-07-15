import json
import os

import httpx

# free tier defaults, swap providers with LLM_BASE_URL and LLM_MODEL env vars
# the latest alias survives model retirements
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-flash-latest"

SYSTEM = """You are an SRE agent investigating a production incident on a kubernetes microservices cluster.
You get the firing alert and the repo's recent commits, some with diffs. Rank up to 3 commits most likely
to have caused this incident. Only name a commit if the diff or message plausibly explains the alert -
an empty suspect list is a valid answer. Config changes (flags, limits, thresholds) count as much as code.

Respond with JSON only, no prose, no code fences:
{"suspects": [{"sha": "...", "confidence": "high|medium|low", "reasoning": "one or two sentences"}],
 "assessment": "one-paragraph summary of what you think happened"}"""


class CulpritRanker:
    """Talks to any openai compatible chat endpoint so the provider is swappable through env vars."""

    def __init__(self, client: httpx.AsyncClient | None = None, model: str | None = None):
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        if client is not None:
            self.http = client
        else:
            base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
            api_key = os.environ.get("LLM_API_KEY", "")
            self.http = httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=60,
            )

    async def rank(self, alert: dict, commits: list[dict], diffs: dict[str, str]) -> dict:
        r = await self.http.post(
            "/chat/completions",
            json={
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": self._prompt(alert, commits, diffs)},
                ],
            },
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            result = json.loads(text)
            result["model"] = self.model
            return result
        except json.JSONDecodeError:
            # keep the raw output so a bad response is debuggable from the incident log
            return {"suspects": [], "assessment": "", "parse_error": True, "raw": text[:2000], "model": self.model}

    def _prompt(self, alert: dict, commits: list[dict], diffs: dict[str, str]) -> str:
        lines = [
            "## Alert",
            json.dumps(alert, indent=2),
            "",
            "## Recent commits (newest first)",
        ]
        for c in commits:
            lines.append(f"- {c['sha']} | {c['date']} | {c['author']} | {c['message']}")
        lines.append("")
        lines.append("## Diffs for the most recent commits")
        for sha, diff in diffs.items():
            lines.append(f"### {sha}")
            lines.append(diff or "(empty diff)")
        return "\n".join(lines)
