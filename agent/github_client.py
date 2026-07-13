import os

import httpx

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Pulls recent commits and diffs - the raw material for culprit ranking."""

    def __init__(self, repo: str | None = None, token: str | None = None, client: httpx.AsyncClient | None = None):
        self.repo = repo or os.environ.get("GITHUB_REPO", "Nikil0527/Agentic-Commit-Flagger")
        token = token or os.environ.get("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = client or httpx.AsyncClient(base_url=GITHUB_API, headers=headers, timeout=15)

    async def recent_commits(self, limit: int = 20) -> list[dict]:
        r = await self.http.get(f"/repos/{self.repo}/commits", params={"per_page": limit})
        r.raise_for_status()
        return [
            {
                "sha": c["sha"][:12],
                "message": c["commit"]["message"].splitlines()[0],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"],
            }
            for c in r.json()
        ]

    async def commit_diff(self, sha: str, max_chars: int = 4000) -> str:
        # per-commit call, so only fetch diffs for shortlisted suspects - keeps rate limits sane
        r = await self.http.get(f"/repos/{self.repo}/commits/{sha}")
        r.raise_for_status()
        chunks = []
        for f in r.json().get("files", []):
            chunks.append(f"--- {f['filename']}\n{f.get('patch', '')}")
        return "\n".join(chunks)[:max_chars]
