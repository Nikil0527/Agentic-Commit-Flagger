# Agentic-Commit-Flagger

An autonomous incident-response agent that can track commit issues when outages occur

When a monitoring alert fires, the agent investigates on its own: it reviews recent commits and their diffs, flags the most likely culprit with reasoning, pulls up the relevant runbook, estimates how many users are affected, and posts a concise incident brief to the team. Once the incident is resolved, it drafts a postmortem from its own record of what happened.

It diagnoses and recommends — it never applies fixes. A human makes every remediation decision

Built and tested against a Kubernetes microservices environment where failures are deliberately injected to validate the agent's accuracy
