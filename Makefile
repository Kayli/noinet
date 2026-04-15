
.PHONY: venv devcontainer-run install run report test lint container-build container-run container-report

install:
	python3 -m pip install --upgrade pip
	python3 -m pip install --upgrade ".[dev]"

run:
	python3 -m noinet.ping_inet

report:
	python3 -m noinet.ping_inet_report --coarse day

test:
	pytest -q

lint:
	python3 -m pylint noinet tests


# Container related variables and targets
# this is useful on older machines that can't run devcontainers, but can run docker or podman
CONTAINER_CMD := $(shell if command -v docker >/dev/null 2>&1; then echo docker; elif command -v podman >/dev/null 2>&1; then echo podman; else echo; fi)
IMAGE := noinet-dev:latest
DOCKERFILE := Dockerfile.app
PWD := $(shell pwd)

container-build:
	@if [ -z "$(CONTAINER_CMD)" ]; then \
		echo "Please install docker or podman to build the container."; exit 1; \
	fi; \
	printf "Using %s to build container\n" "$(CONTAINER_CMD)"; \
	$(CONTAINER_CMD) build -f $(DOCKERFILE) -t $(IMAGE) .

container-run: container-build
	printf "Using %s to run container\n" "$(CONTAINER_CMD)"; \
	$(CONTAINER_CMD) run --rm -it --cap-add=NET_RAW -v "$(PWD)":/workspaces/noinet -w /workspaces/noinet $(IMAGE) python3 -m noinet.ping_inet

container-report: container-build
	printf "Using %s to run report in container\n" "$(CONTAINER_CMD)"; \
	$(CONTAINER_CMD) run --rm -it -v "$(PWD)":/workspaces/noinet -w /workspaces/noinet $(IMAGE) python3 -m noinet.ping_inet_report --coarse day
