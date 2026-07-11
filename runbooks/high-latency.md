# high latency

failure_class: latency — a service is up and answering, just slowly. requests succeed but p99 crosses 1s.

## symptoms

- HighP99Latency fires (PrometheusRule commit-flagger-alerts, monitoring ns). rule:
  `histogram_quantile(0.99, sum by (job, le) (rate(http_server_request_duration_seconds_bucket[5m]))) > 1` for 5m.
- webshop at localhost:30080 feels sluggish. pages render, checkout completes, everything just takes seconds.
- error alerts (HighErrorRate, GrpcHighErrorRate) stay quiet. slow is not broken — if errors fire too, go read error-rate-spike.md first.

## quick checks

```
make prometheus              # localhost:9090, run the queries below
make grafana                 # localhost:3000 admin/admin, eyeball latency panels
kubectl get pods -n demo     # restarts or pending pods?
kubectl top pods -n demo     # who is eating cpu right now
```

find the slowest job:

```
topk(3, histogram_quantile(0.99, sum by (job, le) (rate(http_server_request_duration_seconds_bucket[5m]))))
```

## diagnosis

first question: is everything slow, or just the tail? compare p99 to p50 for the flagged job:

```
histogram_quantile(0.50, sum by (job, le) (rate(http_server_request_duration_seconds_bucket{job="<job>"}[5m])))
```

- p50 high too = the whole service is slow. think cpu saturation, throttling, or a slow downstream dependency.
- only p99 high = tail latency. a slow subset — cache misses, gc pauses, one bad pod out of several.

if the whole service is slow, check cpu throttling. this is the usual cause here:

```
rate(container_cpu_cfs_throttled_periods_total{namespace="demo"}[5m])
```

nonzero and climbing means the container keeps hitting its cpu limit. cross-check with `kubectl top pods -n demo`.

known causes in this cluster:
- ad service burning cpu (this is exactly what the high-cpu chaos fault does). ad slows down, frontend waits on it, page p99 climbs.
- slow image loads from image-provider dragging down frontend page times.

check whether a chaos flag is on before digging deeper:

```
kubectl get cm flagd-config -n demo -o jsonpath='{.data.demo\.flagd\.json}'
```

look-alikes: restarts climbing is pod-crash-loop.md, 5xx or non-OK grpc is error-rate-spike.md. latency means pods healthy, responses fine, just slow.

## mitigation

a human does all of this. never auto-remediate.

- chaos flag on: `./chaos/inject.sh reset`, then `kubectl rollout restart deployment/flagd -n demo` so flagd picks up the configmap change.
- cpu throttled with no flag set: raise the cpu limit on that deployment yourself and watch p99 recover. don't script it.
- tail-only latency isolated to one pod: delete the pod, let it reschedule, see if p99 drops.
- started right after a deploy: `kubectl rollout history deployment/<svc> -n demo` and roll back if the timing lines up.

## notes

- drill this: `./chaos/inject.sh high-cpu` makes ad burn cpu, HighP99Latency fires in a few minutes. practice walking the topk query down to ad.
- load-generator drives constant traffic, so a quiet graph means broken scraping, not a quiet shop.
- histogram_quantile clamps at the top bucket boundary — a flat p99 line at a suspiciously round number means the real latency is above the biggest bucket.
- related: error-rate-spike.md, pod-crash-loop.md, memory-saturation.md.
