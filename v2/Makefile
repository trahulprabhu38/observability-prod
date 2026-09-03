# Convenience wrapper. `make help` lists everything.
.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help up down restart ps logs pull validate reload-prometheus reload-alloy \
        prom-targets prom-rules alloy-ui ecs-up nuke

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start the whole stack
	$(COMPOSE) up -d

down: ## Stop the stack (keeps data volumes)
	$(COMPOSE) down

restart: ## Recreate all containers
	$(COMPOSE) up -d --force-recreate

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Tail logs of all services (Ctrl-C to stop).  make logs S=prometheus for one
	$(COMPOSE) logs -f --tail=100 $(S)

pull: ## Pull newer images
	$(COMPOSE) pull

validate: ## Lint prometheus + alertmanager + otel configs without starting anything
	$(COMPOSE) run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml
	$(COMPOSE) run --rm --no-deps --entrypoint amtool alertmanager check-config /etc/alertmanager/alertmanager.yml
	$(COMPOSE) run --rm --no-deps otel-collector validate --config=/etc/otelcol-contrib/config.yaml

reload-prometheus: ## Hot-reload prometheus.yml + rules (no restart)
	curl -sf -X POST http://localhost:9090/-/reload && echo "prometheus reloaded"

reload-alloy: ## Hot-reload the Alloy config (no restart)
	curl -sf -X POST http://localhost:12345/-/reload && echo "alloy reloaded"

prom-targets: ## Print scrape target health as a table
	@curl -sf http://localhost:9090/api/v1/targets | \
	 python3 -c 'import json,sys;[print(f"{t[\"labels\"][\"job\"]:22} {t[\"scrapeUrl\"]:45} {t[\"health\"]}") for t in json.load(sys.stdin)["data"]["activeTargets"]]'

prom-rules: ## Show loaded recording/alerting rules and their state
	@curl -sf 'http://localhost:9090/api/v1/rules' | python3 -m json.tool

alloy-ui: ## Open the Alloy pipeline UI
	@echo "http://localhost:12345"

ecs-up: ## Start the stack WITH the ECS/CloudWatch exporter (needs AWS creds in .env)
	$(COMPOSE) --profile ecs up -d

nuke: ## Stop AND delete all data volumes (irreversible)
	$(COMPOSE) down -v
