# postmortem inc-20260722-210108-4a43a8

## summary
The `otel-demo/checkout` microservice triggered a `GrpcHighErrorRate` alert when its gRPC error rate exceeded 9%, impacting roughly 10% of requests. The incident response agent successfully fetched recent commits, ranked the culprits, and posted an incident brief identifying a faulty feature flag configuration change.

## root cause
Commit `284a45403f03` ("disable product catalog failure flag") modified `infra/demo-flags.json`, altering feature flag variants used for fault injection and demo behaviors, which directly triggered the service gRPC error spike.

## action items
- [ ] Add pre-merge validation checks for `infra/demo-flags.json` changes to prevent unintended fault injection in production.
- [ ] Implement automated rollback mechanisms for flagged configuration changes when error rate thresholds are breached.
- [ ] Improve monitoring dashboards to provide clearer visibility into active feature flag states and their direct impact on microservice error rates.
- [ ] Update the `error-rate-spike.md` runbook to include specific verification steps for feature flag configurations after resets.

## timeline
- 2026-07-23T01:01:08+00:00 alert_received GrpcHighErrorRate
- 2026-07-23T01:01:08+00:00 commits_fetched
- 2026-07-23T01:01:11+00:00 culprits_ranked top suspect 284a45403f03
- 2026-07-23T01:01:11+00:00 runbook_matched error-rate-spike.md
- 2026-07-23T01:01:11+00:00 impact_estimated ~10% of requests to otel-demo/checkout failing at 0.0 req/s
- 2026-07-23T01:01:11+00:00 brief_posted
- 2026-07-23T01:01:27+00:00 resolved manual
