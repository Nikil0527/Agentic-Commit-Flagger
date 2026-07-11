# downstream dependency failure (cascading error spike)

failure_class=error-spike, cascading variant: one broken upstream (product-catalog) drags its callers (checkout, frontend) into alerting too, so several services look broken but only one actually is.

## symptoms

- GrpcHighErrorRate (failure_class=error-spike) firing for two or more jobs at once, usually checkout and product-catalog together.
- HighErrorRate may also fire for frontend since it ends up serving 5xx to the browser.
- users see product pages failing and PlaceOrder erroring out on the webstore at localhost:30080.
- pods all look healthy: Running, 0 restarts, no OOMKilled. that's the tell this is an error cascade, not a crash.

## quick checks

```
kubectl get pods -n demo
```
everything Running with 0 restarts rules out crash-loop.

```
make prometheus
```
opens localhost:9090. graph the alert expression per job:

```
sum by (job) (rate(rpc_server_duration_milliseconds_count{rpc_grpc_status_code!="0"}[5m]))
/ sum by (job) (rate(rpc_server_duration_milliseconds_count[5m]))
```
this is the GrpcHighErrorRate query. anything over 0.05 is alerting territory.

```
kubectl logs deploy/checkout -n demo --tail=50
```
checkout logs name the upstream call that failed.

```
kubectl get cm flagd-config -n demo -o jsonpath='{.data.demo\.flagd\.json}'
```
check whether a chaos fault flag is switched on (the chaos CLI writes here).

## diagnosis

victim vs culprit is the whole game. walk the call graph the way the webshop does:
frontend -> checkout -> product-catalog / payment / cart.
the deepest alerting service in that chain is the culprit. everything above it is a victim.

- compare error start times across jobs in prometheus (graph tab, not console). the culprit's error rate rises first; checkout follows shortly after. don't trust alert firing order — the 2m `for` clause can shuffle it.
- grpc code 13 (internal) propagates. product-catalog GetProduct returns 13, checkout wraps it and its own PlaceOrder starts returning 13 too. if every checkout error log mentions product-catalog, checkout is a victim.
- look-alikes:
  - payment-failure fault: errors confined to checkout PlaceOrder and the payment job (payment rejects 90% of charges, so GrpcHighErrorRate fires for payment too). browsing stays healthy - payment is the culprit, checkout the victim.
  - PodCrashLooping (failure_class=crash-loop): restarts climbing, different runbook.
  - HighP99Latency (failure_class=latency): requests slow but succeeding, no error-spike alerts.

## mitigation

no auto-remediation on this cluster. a human does this:

1. if a fault flag is on in flagd-config, turn it off and restart flagd so it actually picks up the configmap:

```
./chaos/inject.sh reset
kubectl rollout restart deployment/flagd -n demo
```

2. if no flag is on, check whether the culprit just got deployed:

```
kubectl rollout history deployment/product-catalog -n demo
```

roll back by hand if a fresh revision lines up with when errors started.
3. fix the upstream only. do not restart checkout or frontend — victims recover on their own within a couple minutes once product-catalog is healthy, and restarting them just muddies the timeline.
4. confirm recovery: the error-rate query drops under 0.05 for every job and the alerts resolve in alertmanager (make alertmanager, localhost:9093).

## notes

- flagd does not hot-reload flagd-config. editing the configmap without a rollout restart changes nothing. bites everyone once.
- GrpcHighErrorRate needs >5% non-OK sustained for 2m, so culprit and victim alerts can land minutes apart. read the raw rates, not the alert timestamps.
- load-generator keeps steady traffic flowing, so error rates are meaningful even when nobody is clicking the store.
- related: error-rate-spike.md (covers the non-cascading payment-failure pattern), pod-crash-loop.md, memory-saturation.md, high-latency.md.
