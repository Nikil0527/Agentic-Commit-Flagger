# memory-saturation

a container's memory working set is closing in on its limit — nothing is dead yet, but an OOM kill is coming if nobody acts.

## symptoms

- PodMemorySaturation firing (failure_class=`memory-saturation`, defined in PrometheusRule `commit-flagger-alerts` in the `monitoring` namespace). rule: container working set > 95% of the memory limit for 5 minutes.
- users see nothing yet. this is the early-warning alert. ignore it and the kernel OOM kills the container, it restarts, memory refills, and you graduate to PodCrashLooping (failure_class=`crash-loop`).
- the accounting container never fires this — it's excluded from the rule because its jvm sits at ~98% of its limit by design. that's normal, not an incident.
- in this demo cluster the usual suspect is `email` (that's the chaos memory-leak target).

## quick checks

```
kubectl get pods -n demo
```
restarts already ticking up? then OOM kills have started and this is really a crash-loop.

```
kubectl describe pod <pod> -n demo
```
check Last State. `OOMKilled` means we're past saturation and into kills.

```
make prometheus
```
then at localhost:9090, see who's close to the ceiling:

```
container_memory_working_set_bytes{namespace="demo", container!="", container!="accounting"}
  / on (namespace, pod, container)
kube_pod_container_resource_limits{resource="memory", namespace="demo"} > 0.8
```

```
kubectl get cm flagd-config -n demo -o jsonpath='{.data.demo\.flagd\.json}'
```
is a chaos flag still on? someone may have run a drill and forgotten to reset.

```
kubectl rollout history deployment/<svc> -n demo
```
did a new revision land right before the memory climbed?

## diagnosis

main question: leak or legitimate load?

- leak: working set climbs steadily with traffic and never plateaus. graph it in grafana (`make grafana`, localhost:3000, admin/admin) — a straight ramp, or a sawtooth that resets to baseline after each restart, is a leak. the demo memory-leak fault does exactly this: email leaks a little per request, so more traffic = faster climb.
- legitimate load: usage steps up right after a deploy or traffic change, then holds flat at the new level. if `rollout history` shows a fresh revision at the moment of the jump, the new code just needs more memory (bigger cache, new dependency) — not a leak.
- chaos drill: if `./chaos/inject.sh memory-leak` was run, email is the pod and the flagd config check above will show it.
- look-alike: crash-loop. PodMemorySaturation fires before the first kill; PodCrashLooping fires after kills repeat (>3 restarts in 15m). if both are firing, go to pod-crash-loop.md — the saturation alert is just telling you why.

## mitigation

a human does all of this. never auto-remediate.

- chaos or leftover flag: `./chaos/inject.sh reset`, and make sure the flagd deployment got rollout-restarted so it picks up the configmap change. then `kubectl rollout restart deployment/email -n demo` to reclaim the leaked memory.
- real leak: restarting the deployment buys time (resets the sawtooth) but the fix is in the app code. file it against the service owner and note the leak rate so they can size the runway.
- legitimate load: raise the memory limit in the helm values, or roll back the deploy if the jump wasn't expected. do not raise the limit for a leak — that only delays the OOM kill.

## notes

- accounting at 98% of limit is fine forever. it's excluded from the rule on purpose. don't "fix" it.
- 95% for 5m gives you runway, but under the memory-leak fault with load-generator traffic the gap to the first OOM kill can be minutes.
- drill this with `./chaos/inject.sh memory-leak` and clean up with `./chaos/inject.sh reset`.
- related: pod-crash-loop.md (what this becomes if ignored, plus the flagd-ui instant-OOM story — instant kill at a generous limit means bad image, not undersizing).
