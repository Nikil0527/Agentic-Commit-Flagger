CLUSTER_NAME = commit-flagger

.PHONY: cluster-up cluster-down status

cluster-up:
	kind create cluster --name $(CLUSTER_NAME) --config infra/kind-config.yaml

cluster-down:
	kind delete cluster --name $(CLUSTER_NAME)

status:
	kubectl cluster-info --context kind-$(CLUSTER_NAME)
	kubectl get pods -A
