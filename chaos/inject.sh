#!/usr/bin/env bash
# chaos cli - inject reproducible faults into the demo app
set -euo pipefail

NS=demo
CM=flagd-config
KEY='demo.flagd.json'
TMP="$(mktemp)"
trap 'rm -f "$TMP" "$TMP.new"' EXIT

usage() {
  cat <<'EOF'
usage: inject.sh <fault> | reset | status | list

faults:
  error-spike       product-catalog fails GetProduct, cascades into checkout
  payment-failure   payment rejects 90% of charge requests
  memory-leak       email service leaks memory on every request
  high-cpu          ad service burns cpu, latency climbs
  cache-failure     recommendation service cache breaks
  kafka-lag         kafka queue overload plus consumer delay
  probe-failure     cart readiness probe starts failing
  crash-loop        squeeze email memory limit until it oom-loops

reset   turn all faults off and restore resource limits
status  show which faults are currently active
EOF
}

flags_json() {
  kubectl get cm "$CM" -n "$NS" -o jsonpath='{.data.demo\.flagd\.json}'
}

# flags live in a configmap; flagd only rereads it after a restart
set_flag() {
  flags_json > "$TMP"
  awk -v flag="\"$1\"" -v val="\"$2\"" '
    index($0, flag) { inflag=1 }
    inflag && /"defaultVariant"/ { sub(/"defaultVariant": *"[^"]*"/, "\"defaultVariant\": " val); inflag=0 }
    { print }' "$TMP" > "$TMP.new"
  kubectl create configmap "$CM" -n "$NS" --from-file="$KEY"="$TMP.new" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl rollout restart deployment/flagd -n "$NS" >/dev/null
  echo "flag $1 -> $2"
}

case "${1:-}" in
  error-spike)     set_flag productCatalogFailure on ;;
  payment-failure) set_flag paymentFailure "90%" ;;
  memory-leak)     set_flag emailMemoryLeak "10x" ;;
  high-cpu)        set_flag adHighCpu on ;;
  cache-failure)   set_flag recommendationCacheFailure on ;;
  kafka-lag)       set_flag kafkaQueueProblems on ;;
  probe-failure)   set_flag failedReadinessProbe on ;;
  crash-loop)
    kubectl set resources deployment/email -n "$NS" -c email --requests=memory=16Mi --limits=memory=16Mi
    echo "email squeezed to 16Mi, oom loop incoming" ;;
  reset)
    flags_json | sed 's/"defaultVariant": *"[^"]*"/"defaultVariant": "off"/g' > "$TMP.new"
    kubectl create configmap "$CM" -n "$NS" --from-file="$KEY"="$TMP.new" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl rollout restart deployment/flagd -n "$NS" >/dev/null
    kubectl patch deployment/email -n "$NS" --type json -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources","value":{"limits":{"memory":"100Mi"}}}]' >/dev/null
    echo "all faults off" ;;
  status)
    echo "active flags:"
    flags_json | awk '
      /^    "[a-zA-Z]+": \{/ { gsub(/[":{ ]/,""); name=$0 }
      /"defaultVariant"/ && !/"off"/ { print "  " name " = " $2 }'
    limit=$(kubectl get deploy email -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}')
    [ "$limit" != "100Mi" ] && echo "  email memory squeezed ($limit)" || true ;;
  list) usage ;;
  *) usage; exit 1 ;;
esac
