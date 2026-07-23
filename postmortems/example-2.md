# postmortem inc-20260722-214707-df21f1

## summary
The `otel-demo/checkout` service experienced a high gRPC error rate, failing approximately 40% of its requests. The incident was detected via Prometheus alert `GrpcHighErrorRate` and investigated using the incident response agent, which matched the `downstream-dependency-failure` runbook and guided manual remediation.

## root cause
The incident was triggered by a downstream dependency or feature flag configuration issue. While commit `284a45403f03` ("disable product catalog failure flag") modified failure flags, it pointed to a downstream dependency rather than the checkout service directly, causing cascading failures.

## action items
- [ ] Implement automated rollback or remediation for known downstream dependency failure flags
- [ ] Improve observability linking upstream checkout errors directly to downstream service health
- [ ] Add pre-deployment validation for feature flag and chaos configuration changes
- [ ] Update runbooks to include automated commands for resetting flagd and restarting deployments

## timeline
- 2026-07-23T01:47:07+00:00 alert_received GrpcHighErrorRate
- 2026-07-23T01:47:08+00:00 commits_fetched
- 2026-07-23T01:47:11+00:00 culprits_ranked top suspect 284a45403f03
- 2026-07-23T01:47:11+00:00 runbook_matched downstream-dependency-failure.md
- 2026-07-23T01:47:11+00:00 impact_estimated ~40% of requests to otel-demo/checkout failing at 0.0 req/s
- 2026-07-23T01:47:11+00:00 brief_posted
- 2026-07-23T01:47:18+00:00 resolved manual
