from agent.runbooks import DEFAULT_RUNBOOK_DIR, RunbookIndex


def make_runbooks(tmp_path):
    (tmp_path / "error-rate-spike.md").write_text(
        "# error rate spike\ngrpc errors and 5xx failures above threshold\n"
        "## mitigation\nroll back the bad deploy\ncheck the feature flags\n## notes\nstuff",
        encoding="utf-8",
    )
    (tmp_path / "pod-crash-loop.md").write_text(
        "# pod crash loop\ncontainers restarting oom killed exit codes\n"
        "## mitigation\ndescribe the pod and read last state\n## notes\nstuff",
        encoding="utf-8",
    )
    return RunbookIndex(runbook_dir=tmp_path)


def test_matches_the_right_runbook(tmp_path):
    idx = make_runbooks(tmp_path)
    hit = idx.match("GrpcHighErrorRate error-spike grpc error rate above 5%")
    assert hit["runbook"] == "error-rate-spike.md"
    assert "roll back" in hit["mitigation"]


def test_crash_query_matches_crash_doc(tmp_path):
    idx = make_runbooks(tmp_path)
    hit = idx.match("PodCrashLooping crash-loop container restarting oom")
    assert hit["runbook"] == "pod-crash-loop.md"


def test_no_overlap_returns_none(tmp_path):
    idx = make_runbooks(tmp_path)
    assert idx.match("zzz qqq xyzzy") is None


def test_empty_dir_returns_none(tmp_path):
    idx = RunbookIndex(runbook_dir=tmp_path / "nope")
    assert idx.match("anything") is None


def test_real_runbooks_match_real_alerts():
    idx = RunbookIndex(DEFAULT_RUNBOOK_DIR)
    cases = {
        # both docs cover a product catalog error spike, the cascade doc is the more specific hit
        "GrpcHighErrorRate error-spike grpc error rate above 5% product-catalog": (
            "error-rate-spike.md",
            "downstream-dependency-failure.md",
        ),
        "PodCrashLooping crash-loop restarts oomkilled": ("pod-crash-loop.md",),
        "PodMemorySaturation memory-saturation working set above 95% of limit": ("memory-saturation.md",),
        "HighP99Latency latency p99 above 1s slow requests": ("high-latency.md",),
    }
    for query, expected in cases.items():
        hit = idx.match(query)
        assert hit and hit["runbook"] in expected, f"{query} -> {hit}"
