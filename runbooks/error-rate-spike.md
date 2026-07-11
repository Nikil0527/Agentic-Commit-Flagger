# error rate spike (error-spike)

a service in the demo namespace is failing a chunk of its requests — grpc non-OK statuses or http 5xx — above the 5% alert threshold.

## symptoms

- GrpcHighErrorRate firing: >5% of a job's grpc requests have `rpc_grpc_status_code!="0"` over 5m, sustained 2m. failure_class=error-spike.
- HighErrorRate firing: same idea for http, `http_response_status_code=~"5.."` on `http_server_request_duration_seconds_count`. failure_class=error-spike.
- webstore at localhost:30080 shows broken product pages or checkouts that error out. load-generator failure counts climb.
- multiple alerts at once usually means one cascade, not several root causes.

## quick checks

```
kubectl get pods -n demo
```
everything Running? if restarts are climbing this might be pod-crash-loop.md instead.

```
kubectl rollout history deployment/<svc> -n demo
```
did the failing service just deploy? recent deploy = prime suspect.

```
kubectl get cm flagd-config -n demo -o jsonpath='{.data.demo\.flagd\.json}'
```
chaos faults (error-spike, payment-failure) work through flagd feature flags, so any non-default flag here explains a lot.

```
kubectl logs <pod> -n demo --tail=100
```
read the actual error. grpc status 13 INTERNAL in checkout logs usually points at a downstream dep, not checkout itself.

## diagnosis

find the failing service and method. open prometheus (`make prometheus`, localhost:9090):

```
sum by (job, rpc_method) (rate(rpc_server_duration_milliseconds_count{rpc_grpc_status_code!="0"}[5m]))
```

http version:

```
sum by (job, http_route) (rate(http_server_request_duration_seconds_count{http_response_status_code=~"5.."}[5m]))
```

isolated vs cascading:
- one job failing, rest healthy: root cause is that service. check its deploy history and flags.
- several jobs failing: follow the call graph. product-catalog failing GetProduct also breaks checkout PlaceOrder — checkout returns grpc status 13 INTERNAL because its own GetProduct call fails. fix product-catalog and checkout recovers by itself.
- errors confined to PlaceOrder and the payment job: that's the payment-failure pattern (payment rejects 90% of charges). browsing keeps working, only checkout breaks.

look-alikes:
- HighP99Latency (failure_class=latency) firing without error alerts means slow, not failing. different runbook.
- errors plus restarts means the errors are a symptom of crash-loop, not the disease.

## mitigation

a human does all of this. no auto-remediation on this cluster, ever.

1. chaos flag left on: run `./chaos/inject.sh reset`, then `kubectl rollout restart deployment/flagd -n demo` so flagd picks up the configmap change.
2. bad deploy: `kubectl rollout undo deployment/<svc> -n demo`. only roll back the root-cause service — downstreams like checkout heal once their dep is healthy.
3. neither: save logs first (`kubectl logs <pod> -n demo --previous` if it restarted) before restarting anything, then escalate.

## notes

- fault injection is flag-driven here: `chaos/inject.sh` edits the flagd-config configmap (key demo.flagd.json) and flagd must be rollout-restarted to see it. suspect flags before blaming code.
- cascades look like multi-service outages. group the error PromQL by job first, then by rpc_method, and walk the call chain down until errors stop.
- alert source: PrometheusRule commit-flagger-alerts in the monitoring namespace.
- related: pod-crash-loop.md, high-latency.md, memory-saturation.md
