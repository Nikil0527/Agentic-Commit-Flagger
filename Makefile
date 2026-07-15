CLUSTER_NAME = commit-flagger

.PHONY: cluster-up cluster-down status deploy monitoring alerts grafana prometheus alertmanager

cluster-up:
	kind create cluster --name $(CLUSTER_NAME) --config infra/kind-config.yaml

cluster-down:
	kind delete cluster --name $(CLUSTER_NAME)

status:
	kubectl cluster-info --context kind-$(CLUSTER_NAME)
	kubectl get pods -A

deploy:
	helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
	helm repo update
	helm upgrade --install demo open-telemetry/opentelemetry-demo -n demo --create-namespace -f infra/demo-app-values.yaml

monitoring:
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update
	helm upgrade --install monitoring prometheus-community/kube-prometheus-stack -n monitoring --create-namespace -f infra/monitoring-values.yaml

alerts:
	kubectl apply -f infra/alert-rules.yaml

# UIs are not exposed outside the cluster so port forward to reach them locally
grafana:
	kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80

prometheus:
	kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090

alertmanager:
	kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-alertmanager 9093:9093
