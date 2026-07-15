#!/usr/bin/env bash
# chaos cli for injecting reproducible faults into the demo app
set -euo pipefail

NS=demo
CM=flagd-config
KEY='demo.flagd.json'
# tracked in git so a fault injection is a real config commit the agent can find
FLAGS_FILE="$(cd "$(dirname "$0")/.." && pwd)/infra/demo-flags.json"
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

# each flag is evaluated by one service which holds a stream to flagd and can
# serve stale values after a flagd restart, so the consumer gets bounced too
consumer_of() {
  case "$1" in
    productCatalogFailure)      echo product-catalog ;;
    paymentFailure)             echo payment ;;
    emailMemoryLeak)            echo email ;;
    adHighCpu)                  echo ad ;;
    recommendationCacheFailure) echo recommendation ;;
    kafkaQueueProblems)         echo checkout ;;
    failedReadinessProbe)       echo cart ;;
  esac
}

active_flags() {
  flags_json | awk '
    /^    "[a-zA-Z]+": \{/ { gsub(/[":{ ]/,""); name=$0 }
    /"defaultVariant"/ && !/"off"/ { print name }'
}

apply_flags() {
  kubectl create configmap "$CM" -n "$NS" --from-file="$KEY"="$FLAGS_FILE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl rollout restart deployment/flagd -n "$NS" >/dev/null
}

set_flag() {
  awk -v flag="\"$1\"" -v val="\"$2\"" '
    index($0, flag) { inflag=1 }
    inflag && /"defaultVariant"/ { sub(/"defaultVariant": *"[^"]*"/, "\"defaultVariant\": " val); inflag=0 }
    { print }' "$FLAGS_FILE" > "$TMP.new"
  cp "$TMP.new" "$FLAGS_FILE"
  apply_flags
  target=$(consumer_of "$1")
  [ -n "$target" ] && kubectl rollout restart "deployment/$target" -n "$NS" >/dev/null
  echo "flag $1 -> $2 (restarted flagd + $target)"
  echo "$FLAGS_FILE changed - commit it, that commit is the incident's paper trail"
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
    was_active=$(active_flags)
    sed 's/"defaultVariant": *"[^"]*"/"defaultVariant": "off"/g' "$FLAGS_FILE" > "$TMP.new"
    cp "$TMP.new" "$FLAGS_FILE"
    apply_flags
    for flag in $was_active; do
      target=$(consumer_of "$flag")
      [ -n "$target" ] && kubectl rollout restart "deployment/$target" -n "$NS" >/dev/null && echo "restarted $target"
    done
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
