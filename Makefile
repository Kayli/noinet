.PHONY: run test

run:
	python3 ./ping_inet.py

report:
	python3 ./ping_inet_report.py

test:
	python -m pytest -q
