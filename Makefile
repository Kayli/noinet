
.PHONY: venv devcontainer-run install run report test lint

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

container-run:
	@CMD="$(shell if command -v docker >/dev/null 2>&1; then echo docker; elif command -v podman >/dev/null 2>&1; then echo podman; else echo none; fi)"; \
	if [ "$$CMD" = "none" ]; then \
		echo "Please install docker or podman to run this target."; exit 1; \
	fi; \
	printf "Using %s to build and run container\n" "$$CMD"; \
	$$CMD build -f .devcontainer/Dockerfile -t noinet-dev:latest .; \
	$$CMD run --rm -it --cap-add=NET_RAW -v "$(PWD)":/workspaces/noinet -w /workspaces/noinet noinet-dev:latest python3 -m noinet.ping_inet
