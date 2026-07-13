import json

import httpx
import pytest

from agent.github_client import GitHubClient

COMMITS = [
    {
        "sha": "a1b2c3d4e5f6a7b8c9d0",
        "commit": {
            "message": "enable productCatalogFailure flag\n\nlonger body here",
            "author": {"name": "Nikil0527", "date": "2026-07-13T01:00:00Z"},
        },
    },
    {
        "sha": "f6e5d4c3b2a1f6e5d4c3",
        "commit": {
            "message": "add on-call runbooks",
            "author": {"name": "Nikil0527", "date": "2026-07-12T20:00:00Z"},
        },
    },
]

COMMIT_DETAIL = {
    "sha": "a1b2c3d4e5f6a7b8c9d0",
    "files": [
        {"filename": "infra/demo-flags.json", "patch": '-      "defaultVariant": "off"\n+      "defaultVariant": "on"'},
        {"filename": "README.md", "patch": "+something"},
    ],
}


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.github.com")


@pytest.mark.anyio
async def test_recent_commits_parses_and_trims():
    def handler(request):
        assert "/repos/me/repo/commits" in str(request.url)
        return httpx.Response(200, json=COMMITS)

    gh = GitHubClient(repo="me/repo", client=mock_client(handler))
    commits = await gh.recent_commits(limit=2)

    assert commits[0]["sha"] == "a1b2c3d4e5f6"
    assert commits[0]["message"] == "enable productCatalogFailure flag"
    assert commits[0]["author"] == "Nikil0527"
    assert len(commits) == 2


@pytest.mark.anyio
async def test_commit_diff_joins_files_and_truncates():
    def handler(request):
        return httpx.Response(200, json=COMMIT_DETAIL)

    gh = GitHubClient(repo="me/repo", client=mock_client(handler))
    diff = await gh.commit_diff("a1b2c3d4e5f6")
    assert "demo-flags.json" in diff and "README.md" in diff

    short = await gh.commit_diff("a1b2c3d4e5f6", max_chars=30)
    assert len(short) == 30


@pytest.mark.anyio
async def test_api_error_raises():
    def handler(request):
        return httpx.Response(403, json={"message": "rate limited"})

    gh = GitHubClient(repo="me/repo", client=mock_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await gh.recent_commits()


@pytest.fixture
def anyio_backend():
    return "asyncio"
