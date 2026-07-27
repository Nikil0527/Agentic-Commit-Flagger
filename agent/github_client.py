import asyncio
import os
import subprocess

import httpx

GITHUB_API = "https://api.github.com"


class LocalGitClient:
    """Reads recent commits and diffs from the local git repo so the agent needs no token or network."""

    def __init__(self, repo_dir: str | None = None):
        self.repo = "local"
        self.repo_dir = repo_dir or os.environ.get("GIT_REPO_DIR") or "."

    async def _git(self, *args: str) -> str:
        return await asyncio.to_thread(self._git_sync, *args)

    def _git_sync(self, *args: str) -> str:
        r = subprocess.run(["git", "-C", self.repo_dir, *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:200]}")
        return r.stdout

    async def recent_commits(self, limit: int = 20) -> list[dict]:
        # unit separator between fields so commit messages with spaces stay intact
        out = await self._git("log", f"-{limit}", "--no-color", "--format=%H%x1f%s%x1f%an%x1f%aI")
        commits = []
        for line in out.splitlines():
            if not line.strip():
                continue
            sha, message, author, date = line.split("\x1f")
            commits.append({"sha": sha[:12], "message": message, "author": author, "date": date})
        return commits

    async def commit_diff(self, sha: str, max_chars: int = 4000) -> str:
        out = await self._git("show", "--no-color", "--format=", sha)
        return out[:max_chars]


class GitHubClient:
    """Pulls recent commits and diffs from the GitHub API for repos the agent does not have on disk."""

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
        # one api call per commit so only fetch diffs for shortlisted suspects to keep rate limits sane
        r = await self.http.get(f"/repos/{self.repo}/commits/{sha}")
        r.raise_for_status()
        chunks = []
        for f in r.json().get("files", []):
            chunks.append(f"--- {f['filename']}\n{f.get('patch', '')}")
        return "\n".join(chunks)[:max_chars]


def make_commit_source():
    # local git is the default so a fresh clone works offline with no token
    if os.environ.get("GIT_SOURCE", "local").lower() == "github":
        return GitHubClient()
    return LocalGitClient()
