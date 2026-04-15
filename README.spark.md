PySpark adapter prototype
=========================

This repo includes `scripts/pyspark_adapter.py` — a small PySpark script that
demonstrates reading your ping log format into a Spark DataFrame and
computing coarse outage summaries (hour/day) similar to `noinet.ping_inet_report`.

Run in the devcontainer after installing `pyspark` (system-wide in the
container):

```bash
# from repo root
pip install pyspark
python scripts/pyspark_adapter.py ./ping-8.8.8.8.log --granularity hour
```

Notes:
- The script focuses on batch processing a single log file to produce
  period-level aggregates (outages estimate and total fails). It intentionally
  keeps logic in Spark SQL functions to avoid Python UDF overhead.
- For full parity with `parse_outages` (per-outage start/end windows) we can
  extend the script using window/lead/lag logic or by mapping to pandas for
  post-processing; tell me if you'd like that next.
