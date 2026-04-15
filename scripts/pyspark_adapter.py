#!/usr/bin/env python3
"""Simple PySpark adapter to compute coarse outage summaries from ping logs.

This script demonstrates reading the existing log format into a Spark
DataFrame, extracting timestamps and failure flags, and producing hourly
or daily aggregates similar to `coarse_report`.

Usage (in the devcontainer where pyspark is available):
  python scripts/pyspark_adapter.py /path/to/ping-8.8.8.8.log --granularity hour

The script prints summary lines to stdout.
"""
from __future__ import annotations

import argparse
import re
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window


_TS_RE = r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]"
_FAIL_RE = r"(?i)no answer yet|Destination Host Unreachable|Network is unreachable|No route to host"


def coarse_with_spark(logfile: str, granularity: str = "hour") -> None:
    spark = SparkSession.builder.appName(
        "noinet-pyspark-adapter").getOrCreate()

    # Read file as lines
    df = spark.read.text(logfile).withColumnRenamed("value", "line")

    # Extract timestamp string and cast to timestamp type
    df = df.withColumn("ts_str", F.regexp_extract(F.col("line"), _TS_RE, 1))
    df = df.withColumn("ts", F.to_timestamp(
        F.col("ts_str"), "yyyy-MM-dd HH:mm:ss"))

    # Flags
    df = df.withColumn("is_fail", F.col("line").rlike(_FAIL_RE).cast("int"))
    df = df.withColumn("is_success", F.col(
        "line").rlike(r"\d+ bytes from").cast("int"))

    # Determine start markers for fail runs (transition from non-fail to fail)
    w = Window.orderBy("ts")
    df = df.withColumn("prev_fail", F.lag("is_fail").over(w))
    df = df.withColumn(
        "start_marker",
        F.when((F.col("is_fail") == 1) & ((F.col("prev_fail") == 0)
               | F.col("prev_fail").isNull()), 1).otherwise(0),
    )

    # Period key
    if granularity == "hour":
        period_fmt = "yyyy-MM-dd HH"
    else:
        period_fmt = "yyyy-MM-dd"
    df = df.withColumn("period", F.date_format(F.col("ts"), period_fmt))

    # Aggregate per period
    agg = (
        df.groupBy("period")
        .agg(
            F.sum("start_marker").alias("outages"),
            F.sum("is_fail").alias("total_fails"),
        )
        .orderBy("period")
    )

    for row in agg.collect():
        period = row["period"] if row["period"] is not None else "unknown"
        n = int(row["outages"] or 0)
        lost = int(row["total_fails"] or 0)
        outage_word = "outage" if n == 1 else "outages"
        if period == "unknown":
            print(f"{period}: {n} {outage_word}, {lost} packets lost")
        elif granularity == "hour":
            expected = 3600
            availability = max(0.0, (expected - lost) / expected * 100.0)
            print(
                f"{period}: {n} {outage_word}, {lost} packets lost, {availability:.1f}% up")
        else:
            print(f"{period}: {n} {outage_word}, {lost} packets lost")

    # Totals
    totals = df.agg(F.sum("is_success").alias("successes"),
                    F.sum("is_fail").alias("failures")).collect()[0]
    successes = int(totals["successes"] or 0)
    failures = int(totals["failures"] or 0)
    total = successes + failures
    if total:
        avail = successes / total * 100.0
        print(f"Total: {avail:.1f}% up ({successes} ok, {failures} lost)")

    spark.stop()


def main() -> None:
    p = argparse.ArgumentParser(
        description="PySpark adapter for noinet ping logs")
    p.add_argument("logfile", help="Path to ping logfile")
    p.add_argument("--granularity", choices=("hour", "day"), default="hour")
    args = p.parse_args()
    coarse_with_spark(args.logfile, args.granularity)


if __name__ == "__main__":
    main()
