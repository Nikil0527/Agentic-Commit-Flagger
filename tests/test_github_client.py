import json
import subprocess

import httpx
import pytest

from agent.github_client import GitHubClient, LocalGitClient, make_commit_source

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


def make_git_repo(path):
    def run(*args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "tester")
    (path / "f.txt").write_text("one")
    run("add", ".")
    run("commit", "-q", "-m", "first commit")
    (path / "f.txt").write_text("two")
    run("add", ".")
    run("commit", "-q", "-m", "second commit changes the file")
    return path


@pytest.mark.anyio
async def test_local_git_reads_commits(tmp_path):
    make_git_repo(tmp_path)
    gc = LocalGitClient(repo_dir=str(tmp_path))
    commits = await gc.recent_commits(limit=5)

    assert commits[0]["message"] == "second commit changes the file"
    assert commits[1]["message"] == "first commit"
    assert len(commits[0]["sha"]) == 12
    assert commits[0]["author"] == "tester"


@pytest.mark.anyio
async def test_local_git_diff_shows_changes(tmp_path):
    make_git_repo(tmp_path)
    gc = LocalGitClient(repo_dir=str(tmp_path))
    top = (await gc.recent_commits(limit=1))[0]["sha"]
    diff = await gc.commit_diff(top)
    assert "f.txt" in diff
    assert "two" in diff


def test_make_commit_source_defaults_local(monkeypatch):
    monkeypatch.delenv("GIT_SOURCE", raising=False)
    assert isinstance(make_commit_source(), LocalGitClient)
    monkeypatch.setenv("GIT_SOURCE", "github")
    assert isinstance(make_commit_source(), GitHubClient)
