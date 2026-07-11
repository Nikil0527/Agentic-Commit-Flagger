# kafka consumer lag

no dedicated alert fires for lag - orders pile up in kafka faster than the consumers drain them, so processing gets slow and stale instead of erroring. the loudest signal is sometimes PodMemorySaturation on the kafka pod.

## symptoms

- usually nothing user-facing. the webshop (localhost:30080) loads fine and checkout succeeds, because kafka sits behind the order flow, not in front of it.
- accounting and fraud-detection process orders late. they are the only kafka consumers in this demo — checkout publishes to the `orders` topic and they read from it.
- HighP99Latency (failure_class=latency) mostly stays quiet since the http path doesn't wait on the queue. delayed processing with no error-spike alerts is the tell.
- if the backlog gets big, PodMemorySaturation (failure_class=memory-saturation) can fire on the kafka pod. kafka is the biggest memory user in the demo namespace, so it runs out of headroom first.

## quick checks

```
kubectl get pods -n demo
```
kafka, accounting, fraud-detection should be Running with no fresh restarts.

```
kubectl exec -n demo deploy/kafka -- kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups
```
the script is on PATH in the demo kafka image. watch the LAG column for the accounting and fraud-detection groups. run it twice a minute apart — growing lag is the problem, a flat nonzero number is just catch-up.

```
kubectl top pod -n demo
```
kafka should top the memory list. that's normal, but note how close it is to its limit.

```
kubectl logs deploy/fraud-detection -n demo --tail=50
kubectl logs deploy/accounting -n demo --tail=50
```
are the consumers actually pulling messages, or stuck/rebalancing.

```
kubectl get cm flagd-config -n demo -o jsonpath='{.data.demo\.flagd\.json}'
```
check whether a chaos flag is switched on. the faults in this cluster work through this configmap.

## diagnosis

- lag growing on both groups plus kafka cpu/memory climbing: broker-side queue overload. this is exactly what `./chaos/inject.sh kafka-lag` does (queue overload + consumer delay), so check flagd-config before hunting for a real cause.
- lag growing on one group only: that consumer is the problem, not kafka. check its logs and restart count. if it's restart-looping, PodCrashLooping (failure_class=crash-loop) should also be firing — hand off to pod-crash-loop.md, the lag is a side effect.
- kafka pod OOMKilled (`kubectl describe pod <kafka-pod> -n demo`, look at Last State): that's memory saturation, see memory-saturation.md. a big backlog can push kafka over its limit on this local kind cluster (commit-flagger).
- not this runbook: GrpcHighErrorRate / HighErrorRate (failure_class=error-spike) mean the synchronous path (product-catalog, checkout) is failing. kafka lag does not produce 5xx or non-OK grpc codes.
- sanity check in prometheus (`make prometheus`, localhost:9090): if `histogram_quantile(0.99, sum by (job, le) (rate(http_server_request_duration_seconds_bucket[5m])))` looks normal but consumers are behind, it's queue backlog, not request latency.

## mitigation

no auto-remediation here. a human decides and acts.

- if the kafka-lag chaos flag is on: `./chaos/inject.sh reset`, then `kubectl rollout restart deployment/flagd -n demo` so flagd picks up the configmap change.
- if one consumer is wedged: `kubectl rollout restart deployment/fraud-detection -n demo` (or accounting). restart the consumer, not kafka.
- if input volume is the problem: `kubectl scale deployment/load-generator -n demo --replicas=0` to stop new orders while consumers catch up. scale it back after.
- restarting kafka itself is last resort — in this demo storage is ephemeral, so bouncing the broker throws away the backlog. fine for a demo, but know that's what you did.
- after the fix, rerun the consumer-groups command and watch LAG trend to zero. give it a few minutes before calling it done.

## notes

- drill this on purpose with `./chaos/inject.sh kafka-lag`. remember flags only apply after the flagd rollout restart.
- accounting is deliberately excluded from the PodMemorySaturation rule (its jvm always runs hot), so that alert will never warn you about the accounting consumer. check it by hand.
- alerts live in PrometheusRule commit-flagger-alerts in the monitoring namespace; grafana is `make grafana` (localhost:3000, admin/admin), alertmanager is `make alertmanager` (localhost:9093).
- related: memory-saturation.md, pod-crash-loop.md, error-rate-spike.md, high-latency.md
