# bad config rollout

a deploy or config change shipped bad values, so any failure_class can fire (error-spike, latency, crash-loop, memory-saturation) — the tell is timing, not the alert name.

## symptoms

- any of GrpcHighErrorRate, HighErrorRate, HighP99Latency, PodCrashLooping, PodMemorySaturation starts firing within minutes of a change, not gradually
- users see whatever the broken service does: failed orders (checkout PlaceOrder), broken product pages (product-catalog), slow or dead pages on the webstore at localhost:30080
- a service that was fine yesterday and untouched code-wise suddenly misbehaves — config includes feature flags, so "nobody deployed" does not clear config as a cause

## quick checks

```
kubectl get pods -n demo
```
anything restarting or pending right after a rollout is the suspect

```
kubectl rollout history deployment/<svc> -n demo
```
did anything roll recently? line the revision time up against when the alert fired

```
kubectl get cm flagd-config -n demo -o jsonpath='{.data.demo\.flagd\.json}'
```
flags are config too — check defaultVariants before blaming code

```
kubectl logs <pod> -n demo --previous
```
if the new pod died, the previous container usually logged why

## diagnosis

- in prometheus (make prometheus, localhost:9090) find the exact minute the alert condition went bad, e.g. for gRPC:

```
sum by (job) (rate(rpc_server_duration_milliseconds_count{rpc_grpc_status_code!="0"}[5m]))
/ sum by (job) (rate(rpc_server_duration_milliseconds_count[5m])) > 0.05
```

- if that minute is right after a rollout or configmap edit, it's the change. done narrowing, go mitigate.
- diff the live configmap against git. flagd-config is the live example here: dump demo.flagd.json with the jsonpath above and compare to the checked-in copy. a defaultVariant flipped to "on" looks exactly like a code bug from the outside.
- look-alike: GrpcHighErrorRate (failure_class=error-spike) on product-catalog cascading into checkout with no recent deployment is almost certainly a flag — that is literally what ./chaos/inject.sh error-spike does.
- look-alike: PodCrashLooping (failure_class=crash-loop) after a rollout. kubectl describe pod, check Last State for OOMKilled. killed seconds after start at a generous limit means bad image or startup bug, not undersizing — roll back, don't raise limits.
- gotcha: flagd only reads flagd-config at startup. a flag edit without a flagd rollout restart means the old config is still live — and the next restart can suddenly activate a flag someone changed hours ago. check restartedAt on the flagd deployment before trusting the timeline.

## mitigation

a human does all of this. no auto-remediation on this cluster.

- bad deployment: `kubectl rollout undo deployment/<svc> -n demo` (or `--to-revision=N` from rollout history)
- bad flag: edit flagd-config back (defaultVariant to "off"), then `kubectl rollout restart deployment/flagd -n demo` — flag changes do not take effect without the restart
- leftover chaos: `./chaos/inject.sh reset`, then restart flagd
- confirm the alert clears in alertmanager (make alertmanager, localhost:9093) and the PromQL above drops back under 0.05
- write down which revision you rolled back to — undo creates a new revision and history gets confusing fast

## notes

- real incident from this cluster: the flagd-ui sidecar OOM-looped at every memory limit we tried (250Mi, 500Mi, 1Gi), killed under a second after start. root cause was a broken image, fix was removing the sidecar. lesson: instant OOM kill at generous limits = bad image or startup bug, not undersizing.
- accounting is excluded from PodMemorySaturation (its jvm always runs hot) — don't chase it during a config incident
- the failure_class label tells you the symptom, not the cause. once you've confirmed the cause is a change, this runbook wins over the symptom one.
- related: error-rate-spike.md, high-latency.md, pod-crash-loop.md, memory-saturation.md
