# Agentic-Commit-Flagger

![ci](https://github.com/Nikil0527/Agentic-Commit-Flagger/actions/workflows/ci.yml/badge.svg)

An autonomous incident-response agent that can track commit issues when outages occur

Built and tested against a Kubernetes microservices environment where failures are deliberately injected to validate the agent's accuracy

## How it works

1. **Alert**: Prometheus detects a problem in the demo cluster and Alertmanager sends a webhook to the agent
2. **Investigate**: the agent pulls recent commits and diffs from the GitHub repo
3. **Diagnose**: an LLM ranks the commits most likely to have caused the incident, with reasoning
4. **Runbook**: the matching on-call runbook is retrieved and its mitigation steps attached
5. **Impact**: live Prometheus queries estimate how much traffic is failing and for how long
6. **Brief**: everything lands in one incident brief, logged with the incident
7. **Postmortem**: when a human resolves the incident, the agent drafts a postmortem from its own event log

Every investigation step is added to a per-incident JSONL log, of which the postmortem is based on

## Tech Stack

**Infrastructure**

* kind (Kubernetes in Docker) - local single-node cluster the whole system runs on
* Helm - installs the monitoring stack and the demo app
* OpenTelemetry Demo - ~15-microservice webshop used as the fake production system

**Monitoring**

* Prometheus - scrapes metrics and evaluates the alert rules
* Alertmanager - routes firing alerts to the agent via webhook
* Grafana - dashboards over the cluster metrics

**Agent Service**

* Python 3.12 & FastAPI - receives webhooks and runs the diagnosis pipeline
* httpx - async calls to GitHub, the LLM, and Prometheus
* pytest - test suite run in GitHub Actions CI

**LLM**

* Gemini API (free tier) - ranks culprit commits and drafts postmortems
* OpenAI-compatible interface - swappable to any provider via env vars

**Integrations**

* GitHub REST API - pulls recent commits and diffs to find the culprit
* Prometheus HTTP API - queries live metrics for user-impact estimates

**Chaos + Evaluation**

* Custom chaos CLI (`chaos/inject.sh`) - injects 8 fault types through git-tracked feature flags
* Evaluation harness - scores culprit accuracy, runbook retrieval, and time-to-brief across repeated trials

## Getting Started

Prerequisites: Docker Desktop, kind, kubectl, helm, Python 3.12

```sh
# cluster with monitoring and the demo app
make cluster-up
make monitoring
make deploy
make alerts

# agent service
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on mac and linux
echo LLM_API_KEY=your-free-key-from-aistudio.google.com > .env
.venv/Scripts/python -m uvicorn agent.main:app --host 0.0.0.0 --port 8000

# in a second terminal, keep prometheus reachable for impact estimates
make prometheus
```

Without an LLM key the agent still runs end to end and logs `ranking_skipped`. but diagnosis still requires a free key for access

Or run the agent as a container:

```sh
make docker-build
make docker-run    # reads .env for the key, set GIT_SOURCE=github to read commits over the api
```

### Configuration

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | free key from aistudio.google.com, required for diagnosis |
| `GITHUB_TOKEN` | optional, raises the GitHub API rate limit for repeated runs |
| `GITHUB_REPO` | repo the agent scans for culprit commits, defaults to this one |
| `LLM_MODEL` | override the model, defaults to a Gemini flash model |
| `LLM_BASE_URL` | point at any OpenAI-compatible provider instead of Gemini |
| `PROMETHEUS_URL` | override the Prometheus address for impact queries, defaults to localhost:9090 |

## Testing

```sh
./chaos/inject.sh error-spike     # product-catalog starts failing, checkout degrades with it
git add infra/demo-flags.json
git commit -m "enable product catalog failure flag"
git push                          # this commit is now the culprit for the agent to find
```

Within a few minutes the alert fires and the agent logs its diagnosis. Watch it happen:

```sh
curl localhost:8000/incidents                     # open incidents
cat data/incidents/<incident-id>.jsonl            # every investigation step, including the brief
```

Resolve it like an on-call human would:

```sh
./chaos/inject.sh reset
curl -X POST localhost:8000/incidents/<incident-id>/resolve
cat postmortems/<incident-id>.md                  # the drafted postmortem
```

`./chaos/inject.sh list` shows all eight available faults.

## Actually Running the Tests

```sh
make test
```

## Evaluation

The agent is scored like a benchmark, with the cluster and agent running:

```sh
make eval          # injects every scenario 3x, scores each diagnosis
make eval-report   # prints the results table
```

Each trial injects a fault, commits the change so there is a real culprit commit, waits for the agent to diagnose, then scores whether the top suspect was that commit, whether the right runbook was retrieved, and the time from injection to brief.

Latest run, each scenario injected 3 times:

| scenario | culprit found | runbook correct | median time to brief |
|---|---|---|---|
| error-spike | 3/3 | 3/3 | 4.8 min |
| payment-failure | 3/3 | 3/3 | 3.8 min |
| memory-leak | 3/3 | 3/3 | 5.8 min |
| crash-loop | n/a | 2/3 | 4.5 min |

Culprit commit identified in 9/9 scenarios that inject a committed change. Crash-loop has no culprit commit since it is a resource squeeze rather than a config change, and its aggressive out-of-memory fault occasionally trips its alert too fast to catch, which is why one trial timed out. Results append to `eval/results.jsonl` so interrupted runs resume where they left off.