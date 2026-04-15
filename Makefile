
.PHONY: venv install run report test lint

install:
	python3 -m pip install --upgrade pip
	python3 -m pip install --upgrade ".[dev]"

venv:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install --upgrade ".[dev]"

run:
	python3 -m noinet.ping_inet

report:
	python3 -m noinet.ping_inet_report --coarse day

test:
	pytest -q

lint:
	python3 -m pylint noinet tests
