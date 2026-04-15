
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
container-run:
	sh scripts/container_run.sh run

container-report:
	sh scripts/container_run.sh report
