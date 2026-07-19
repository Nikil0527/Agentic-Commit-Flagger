# Agentic-Commit-Flagger

An autonomous incident-response agent that can track commit issues when outages occur.

When a monitoring alert fires, the agent investigates on its own: it reviews recent commits and their diffs, flags the most likely culprit with reasoning, pulls up the relevant runbook, estimates how much traffic is affected, and produces a concise incident brief. Once the incident is resolved, it drafts a postmortem report from its own record of what happened.

It diagnoses and recommends fixes but never implements them automatically.

Built and tested against a Kubernetes microservices environment where failures are deliberately injected to validate the agent's accuracy.

## How it works

1. **Alert** — Prometheus detects a problem in the demo cluster and Alertmanager sends a webhook to the agent
2. **Investigate** — the agent pulls recent commits and diffs from the GitHub repo
3. **Diagnose** — an LLM ranks the commits most likely to have caused the incident, with reasoning
4. **Runbook** — the matching on-call runbook is retrieved and its mitigation steps attached
5. **Impact** — live Prometheus queries estimate how much traffic is failing and for how long
6. **Brief** — everything lands in one incident brief, logged with the incident
7. **Postmortem** — when a human resolves the incident, the agent drafts a postmortem from its own event log

Every investigation step is appended to a per-incident JSONL log, which is what the postmortem is generated from.

## Tech stack

| Layer | Tool |
|---|---|
| Demo app | OpenTelemetry Demo (~15 microservices) |
| Cluster | kind (Kubernetes in Docker) |
| Monitoring | Prometheus, Alertmanager, Grafana (kube-prometheus-stack) |
| Agent service | Python 3.12, FastAPI |
| LLM | Gemini API free tier, swappable to any OpenAI-compatible provider via env vars |
| Integrations | GitHub REST API |
| Fault injection | Custom chaos CLI (`chaos/inject.sh`) driven by feature flags tracked in git |
| Tests | pytest, 38 tests |

Everything runs locally and free — no cloud account and no paid services.

## Getting started

Prerequisites: Docker Desktop, kind, kubectl, helm, Python 3.12.

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

Without an LLM key the agent still runs end to end and logs `ranking_skipped` — diagnosis needs the free key.

## Break something on purpose

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

## Running the tests

```sh
.venv/Scripts/python -m pytest
```

## Design notes

- **No auto-remediation.** The agent diagnoses and recommends; a human resolves. This is deliberate.
- **Real culprit commits, no fake history.** Fault injection edits a flag file tracked in git, so the commit that broke the cluster is a genuine commit in this repo's history.
- **Provider-agnostic LLM.** The agent talks to any OpenAI-compatible endpoint; the default is the Gemini free tier. Retries, backoff, and serialized calls keep it reliable on free-tier limits.
- **Degrades gracefully.** No LLM key, GitHub down, Prometheus unreachable — each step logs its failure and the rest of the pipeline continues.

## Status

Core pipeline complete and verified end to end. Remaining: evaluation harness with accuracy metrics, CI, demo recording.
