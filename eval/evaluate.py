"""Runs chaos scenarios against the live stack and scores the agent.

Usage: python eval/evaluate.py --trials 3          run missing trials, resumable
       python eval/evaluate.py --report            print the results table
"""

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from statistics import median

import httpx

AGENT = "http://localhost:8000"
ROOT = Path(__file__).resolve().parent.parent
RESULTS = Path(__file__).resolve().parent / "results.jsonl"
INCIDENT_DIR = ROOT / "data" / "incidents"

SCENARIOS = {
    "error-spike": {"alerts": {"GrpcHighErrorRate"}, "runbooks": {"error-rate-spike.md", "downstream-dependency-failure.md"}, "culprit_file": "infra/demo-flags.json"},
    "payment-failure": {"alerts": {"GrpcHighErrorRate"}, "runbooks": {"error-rate-spike.md", "downstream-dependency-failure.md"}, "culprit_file": "infra/demo-flags.json"},
    "high-cpu": {"alerts": {"HighP99Latency"}, "runbooks": {"high-latency.md"}, "culprit_file": "infra/demo-flags.json"},
    "memory-leak": {"alerts": {"PodMemorySaturation", "PodCrashLooping"}, "runbooks": {"memory-saturation.md", "pod-crash-loop.md"}, "culprit_file": "infra/demo-flags.json"},
    "crash-loop": {"alerts": {"PodCrashLooping", "PodMemorySaturation"}, "runbooks": {"pod-crash-loop.md", "memory-saturation.md"}, "culprit_file": None},
}

DETECT_TIMEOUT = 20 * 60
COOLDOWN = 8 * 60


def score_events(events: list[dict], spec: dict, culprit_shas: set[str]) -> dict:
    """Pure scoring of one incident event log, kept separate so it is testable."""
    by_event = {}
    for e in events:
        by_event.setdefault(e.get("event"), e)

    alertname = by_event.get("alert_received", {}).get("data", {}).get("alertname", "")
    suspects = by_event.get("culprits_ranked", {}).get("data", {}).get("suspects", [])
    top_sha = suspects[0].get("sha", "") if suspects else ""
    runbook = by_event.get("runbook_matched", {}).get("data", {}).get("runbook", "")

    brief_seconds = None
    try:
        t_alert = datetime.fromisoformat(by_event["alert_received"]["ts"])
        t_brief = datetime.fromisoformat(by_event["brief_posted"]["ts"])
        brief_seconds = (t_brief - t_alert).total_seconds()
    except (KeyError, ValueError):
        pass

    return {
        "alert_ok": alertname in spec["alerts"],
        "culprit_ok": None if spec["culprit_file"] is None else any(top_sha and s.startswith(top_sha) for s in culprit_shas),
        "runbook_ok": runbook in spec["runbooks"],
        "top_suspect": top_sha,
        "runbook": runbook,
        "brief_seconds": brief_seconds,
    }


def commits_touching(path: str, limit: int = 20) -> set[str]:
    out = subprocess.run(["git", "log", f"-{limit}", "--format=%H", "--", path], capture_output=True, text=True, cwd=ROOT)
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def existing_incident_ids() -> set[str]:
    return {f.stem for f in INCIDENT_DIR.glob("*.jsonl")} if INCIDENT_DIR.exists() else set()


def read_incident(incident_id: str) -> list[dict]:
    path = INCIDENT_DIR / f"{incident_id}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_trial(scenario: str, spec: dict) -> dict:
    known = existing_incident_ids()
    culprits = commits_touching(spec["culprit_file"]) if spec["culprit_file"] else set()

    subprocess.run(["bash", "chaos/inject.sh", scenario], cwd=ROOT, check=True, capture_output=True)
    t0 = time.time()
    print(f"  injected {scenario}, waiting for diagnosis...")

    result = None
    while time.time() - t0 < DETECT_TIMEOUT:
        time.sleep(15)
        for incident_id in existing_incident_ids() - known:
            events = read_incident(incident_id)
            names = {e.get("event") for e in events}
            if "brief_posted" not in names:
                continue
            scored = score_events(events, spec, culprits)
            if not scored["alert_ok"]:
                continue
            scored.update({"scenario": scenario, "incident": incident_id, "detect_seconds": round(time.time() - t0), "ts": datetime.now().isoformat(timespec="seconds")})
            httpx.post(f"{AGENT}/incidents/{incident_id}/resolve", timeout=120)
            result = scored
            break
        if result:
            break

    if result is None:
        result = {"scenario": scenario, "incident": None, "alert_ok": False, "culprit_ok": False, "runbook_ok": False, "detect_seconds": None, "brief_seconds": None, "ts": datetime.now().isoformat(timespec="seconds")}

    subprocess.run(["bash", "chaos/inject.sh", "reset"], cwd=ROOT, check=True, capture_output=True)
    print(f"  reset, cooling down {COOLDOWN // 60} min so alerts clear")
    time.sleep(COOLDOWN)
    return result


def report():
    if not RESULTS.exists():
        print("no results yet")
        return
    rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("| scenario | trials | culprit found | runbook correct | median time to brief |")
    print("|---|---|---|---|---|")
    for scenario in SCENARIOS:
        rs = [r for r in rows if r["scenario"] == scenario]
        if not rs:
            continue
        culprit_rs = [r for r in rs if r.get("culprit_ok") is not None]
        culprit = f"{sum(bool(r['culprit_ok']) for r in culprit_rs)}/{len(culprit_rs)}" if culprit_rs else "n/a"
        runbook = f"{sum(bool(r['runbook_ok']) for r in rs)}/{len(rs)}"
        times = [r["detect_seconds"] for r in rs if r.get("detect_seconds")]
        med = f"{round(median(times) / 60, 1)} min" if times else "n/a"
        print(f"| {scenario} | {len(rs)} | {culprit} | {runbook} | {med} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--scenarios", nargs="*", default=list(SCENARIOS))
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        report()
        return

    httpx.get(f"{AGENT}/health", timeout=5).raise_for_status()
    done = []
    if RESULTS.exists():
        done = [json.loads(line)["scenario"] for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]

    for scenario in args.scenarios:
        remaining = args.trials - done.count(scenario)
        for i in range(remaining):
            print(f"[{scenario}] trial {done.count(scenario) + i + 1}/{args.trials}")
            result = run_trial(scenario, SCENARIOS[scenario])
            with RESULTS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(result) + "\n")
            print(f"  {result}")
    report()


if __name__ == "__main__":
    main()
