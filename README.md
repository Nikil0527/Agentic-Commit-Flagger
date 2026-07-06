# Agentic-Commit-Flagger

An autonomous incident-response agent that can track commit issues when outages occur

When a monitoring alert fires, the agent investigates on its own: it will review recent commits and their diffs, flag the most likely culprit with reasoning, pull up the relevant runbook, estimate how many users are affected, and post a concise incident brief to the team. Once the incident is resolved, it will draft a postmortem report from its own record of what happened.

It diagnoses and recommends fixes but never implements them automatically

Built and tested against a Kubernetes microservices environment where failures are deliberately injected to validate the agent's accuracy
