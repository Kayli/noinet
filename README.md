# noinet

A small Python project for testing network reachability and reporting.

## Installation

Install from source:

```bash
make install
```

## Usage

Run the main modules or the tests. Examples:

```bash
make run    # runs `python -m noinet.ping_inet`
make report # runs `python -m noinet.ping_inet_report`
```

## Tests

Run tests with:

```bash
make test
```

## Files

- `noinet/` — package source
- `tests/` — unit tests


## Uptime reference 

Quick reference (approx. downtime):

99.0% → 87.6 hours/year (≈3.7 days)
99.9% → 8.76 hours/year
99.95% → 4.38 hours/year
99.99% → 52.6 minutes/year
99.999% → 5.3 minutes/year



License: MIT
