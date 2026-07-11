# pod crash loop

crash-loop means a container keeps dying and kubernetes keeps restarting it — usually an OOM kill or a startup failure, not a traffic problem.

## symptoms

- PodCrashLooping fires (failure_class=crash-loop), from PrometheusRule commit-flagger-alerts in the monitoring ns. rule: `increase(kube_pod_container_status_restarts_total{namespace!="kube-system"}[15m]) > 3` for 2m.
- a pod in the demo ns shows CrashLoopBackOff or a climbing RESTARTS count.
- user impact depends on the service. email crashing = order confirmations stop but checkout still works. frontend or frontend-proxy crashing = the webstore at localhost:30080 goes down.
- if callers can't reach the dying service, GrpcHighErrorRate or HighErrorRate (failure_class=error-spike) may fire alongside.

## quick checks

```
kubectl get pods -n demo
```
find the pod with restarts climbing or CrashLoopBackOff.

```
kubectl describe pod <pod> -n demo
```
read Last State. OOMKilled with exit code 137 = memory. anything else = app bug or bad config.

```
kubectl logs <pod> -n demo --previous
```
logs from the container that died, not the fresh replacement.

```
kubectl rollout history deployment/<svc> -n demo
```
did a recent deploy change the image or env?

```
kubectl get cm flagd-config -n demo -o jsonpath='{.data.demo\.flagd\.json}'
```
check if a chaos fault flag is on.

## diagnosis

split on Last State from describe:

- OOMKilled (137), dies after running a while: real memory pressure. leak or undersized limit. if PodMemorySaturation (failure_class=memory-saturation) was firing before the restarts started, it was warning you about exactly this. the crash-loop drill in this cluster squeezes email's memory limit to 16Mi (normal is 100Mi) so it oom-loops on purpose.
- OOMKilled (137), dies instantly even at generous limits: this is NOT undersizing. real incident on this cluster: the flagd-ui sidecar OOM-looped at 250Mi, 500Mi, and 1Gi, killed under a second after start every time. root cause was a broken image, and the fix was removing the sidecar. instant OOM kill at any limit = bad image or startup bug — raising the limit just wastes time.
- non-137 exit code: read `logs --previous`. usually a missing env var, bad config, or a dependency that isn't up yet (e.g. kafka not ready, so accounting or fraud-detection dies on boot).

look-alikes:
- probe-failure fault makes cart go unready (0/1 Ready) but restarts don't climb. that's a readiness problem, not crash-loop.
- PodMemorySaturation alone (working set > 95% of limit for 5m) is the pre-crash stage. handle it before it becomes this.

## mitigation

no auto-remediation on this cluster. a human decides and acts.

1. if a chaos fault is on: `./chaos/inject.sh reset`, then `kubectl rollout restart deployment/flagd -n demo` so flagd picks up the flag change.
2. if a recent deploy changed the image or env: `kubectl rollout undo deployment/<svc> -n demo`.
3. legit OOM (grows, then dies): raise the memory limit in the deploy config and redeploy. deleting the pod does nothing, it dies again.
4. instant OOM / broken image: roll back to a known-good image, or remove the broken container entirely (that's what fixed flagd-ui).
5. watch `kubectl get pods -n demo -w` until restarts flatten and PodCrashLooping resolves in alertmanager (localhost:9093 via `make alertmanager`).

## notes

- drill it yourself: `./chaos/inject.sh crash-loop` (drops email's memory limit to 16Mi). faults ride on feature flags in configmap flagd-config, key demo.flagd.json — flagd needs a rollout restart to pick up changes.
- PodMemorySaturation excludes the accounting container (its jvm always runs hot), but PodCrashLooping excludes nothing outside kube-system. don't assume accounting can't crash-loop.
- exit code 137 without "OOMKilled" in Last State can also be a SIGKILL from a failed liveness probe. describe output tells you which.
- uis: `make prometheus` (localhost:9090) to query the restart counter directly, `make grafana` (localhost:3000, admin/admin) for dashboards.
- related: memory-saturation.md (the warning stage before OOM crash loops), error-rate-spike.md (downstream fallout when a dying service drops requests).
