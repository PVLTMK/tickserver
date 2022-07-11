SHELL = /bin/sh

.DEFAULT_GOAL := help

RUN_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
$(eval $(RUN_ARGS):;@:)

docker_bin := $(shell command -v docker 2> /dev/null)
docker_compose_bin := $(shell command -v docker-compose 2> /dev/null)
pwd := $(shell pwd)

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Start
	docker build -t tr_tick_server:latest .
	docker run -d --env-file ./.env --restart=always --add-host host.docker.internal:host-gateway --name tr_tick_server --log-opt max-size=10m --log-opt max-file=5 -e PYTHONUNBUFFERED:'1' -p 9999:9999 -v $(pwd)/src:/deploy tr_tick_server:latest python3 ./server.py
	docker logs -f tr_tick_server

down: ## Stop
	docker stop tr_tick_server
	docker rm tr_tick_server
