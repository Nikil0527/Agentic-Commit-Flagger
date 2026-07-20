import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
from evaluate import SCENARIOS, score_events

EVENTS = [
    {"ts": "2026-07-19T01:00:00+00:00", "event": "alert_received", "data": {"alertname": "GrpcHighErrorRate"}},
    {"ts": "2026-07-19T01:00:05+00:00", "event": "culprits_ranked",
     "data": {"suspects": [{"sha": "abc123def456", "confidence": "high"}]}},
    {"ts": "2026-07-19T01:00:06+00:00", "event": "runbook_matched", "data": {"runbook": "error-rate-spike.md"}},
    {"ts": "2026-07-19T01:00:07+00:00", "event": "brief_posted", "data": {"text": "..."}},
]


def test_scores_a_clean_hit():
    spec = SCENARIOS["error-spike"]
    out = score_events(EVENTS, spec, culprit_shas={"abc123def456789fullsha"})
    assert out["alert_ok"] is True
    assert out["culprit_ok"] is True
    assert out["runbook_ok"] is True
    assert out["brief_seconds"] == 7.0


def test_wrong_culprit_and_runbook():
    spec = SCENARIOS["error-spike"]
    events = [dict(e) for e in EVENTS]
    events[1] = {"ts": "2026-07-19T01:00:05+00:00", "event": "culprits_ranked", "data": {"suspects": [{"sha": "999999"}]}}
    events[2] = {"ts": "2026-07-19T01:00:06+00:00", "event": "runbook_matched", "data": {"runbook": "kafka-consumer-lag.md"}}
    out = score_events(events, spec, culprit_shas={"abc123def456789fullsha"})
    assert out["culprit_ok"] is False
    assert out["runbook_ok"] is False


def test_crash_loop_skips_culprit_scoring():
    spec = SCENARIOS["crash-loop"]
    events = [dict(EVENTS[0]), dict(EVENTS[3])]
    events[0] = {"ts": "2026-07-19T01:00:00+00:00", "event": "alert_received", "data": {"alertname": "PodCrashLooping"}}
    out = score_events(events, spec, culprit_shas=set())
    assert out["culprit_ok"] is None
    assert out["alert_ok"] is True


def test_missing_events_do_not_crash():
    out = score_events([], SCENARIOS["error-spike"], culprit_shas=set())
    assert out["alert_ok"] is False
    assert out["brief_seconds"] is None
