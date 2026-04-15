#!/usr/bin/env python3
"""Daily coarse outage report (Spark-only).

This module provides a single command-line entry that reads a ping logfile
and prints a daily summary: "YYYY-MM-DD: N outages, M packets lost" and a
final total line. All processing is done with PySpark for speed on larger
logs; the implementation intentionally supports only the daily coarse report
to keep the code minimal.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from typing import Optional, TextIO

from .shared import add_target_and_logfile_args

import re

# Timestamp and failure patterns (same semantics as original implementation)
_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
_FAIL_RE = re.compile(
    r"no answer yet|Destination Host Unreachable|Network is unreachable|No route to host", re.IGNORECASE)
_SUCCESS_RE = re.compile(r"\d+ bytes from")


def _suppress_spark_output_cm():
    """Context manager to silence stdout/stderr during Spark startup."""
    @contextlib.contextmanager
    def _cm():
        fd_null = os.open(os.devnull, os.O_RDWR)
        old_out = os.dup(1)
        old_err = os.dup(2)
        try:
            os.dup2(fd_null, 1)
            os.dup2(fd_null, 2)
            yield
        finally:
            os.dup2(old_out, 1)
            os.dup2(old_err, 2)
            os.close(fd_null)
            os.close(old_out)
            os.close(old_err)

    return _cm()


def _init_spark():
    with _suppress_spark_output_cm():
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.appName(
            "noinet-daily-coarse").getOrCreate()
    try:
        spark.sparkContext.setLogLevel("ERROR")
    except Exception:
        pass
    return spark


def daily_coarse_report(logfile: str, min_fails: int = 3, output: TextIO = sys.stdout, progress: Optional[TextIO] = sys.stderr) -> None:
    """Compute and print a daily coarse outage summary using PySpark.

    :param logfile: path to the ping logfile
    :param min_fails: minimum consecutive failures to count as an outage
    :param output: where to write the textual report (stdout by default)
    :param progress: optional progress stream (stderr by default)
    """
    try:
        from pyspark.sql import functions as F
        from pyspark.sql.window import Window
    except Exception:
        raise SystemExit(
            "PySpark not installed; install pyspark to use this report")

    spark = _init_spark()

    if progress:
        print("[spark] reading logfile...", file=progress, flush=True)
    df = spark.read.text(logfile).withColumnRenamed("value", "line")
    df = df.cache()
    start = time.monotonic()
    try:
        total_lines = df.count()
    except Exception:
        total_lines = None
    if progress:
        elapsed = time.monotonic() - start
        if total_lines is not None:
            print(
                f"[spark] cached {total_lines:,} lines in {elapsed:.1f}s", file=progress, flush=True)
        else:
            print(
                f"[spark] cached (unknown) in {elapsed:.1f}s", file=progress, flush=True)

    # Parse timestamp and flags
    ts_re = _TS_RE.pattern
    df = df.withColumn("ts_str", F.regexp_extract(F.col("line"), ts_re, 1))
    df = df.withColumn("ts", F.to_timestamp(
        F.col("ts_str"), "yyyy-MM-dd HH:mm:ss"))
    df = df.withColumn("is_fail", F.col(
        "line").rlike(_FAIL_RE.pattern).cast("int"))
    df = df.withColumn("is_success", F.col(
        "line").rlike(_SUCCESS_RE.pattern).cast("int"))

    # Detect run starts (transition into failure), assign run ids
    w_order = Window.orderBy("ts")
    df = df.withColumn("prev_fail", F.lag("is_fail").over(w_order))
    df = df.withColumn("start_marker", F.when((F.col("is_fail") == 1) & (
        (F.col("prev_fail") == 0) | F.col("prev_fail").isNull()), 1).otherwise(0))
    w_cum = Window.orderBy("ts").rowsBetween(
        Window.unboundedPreceding, Window.currentRow)
    df = df.withColumn("run_id", F.sum("start_marker").over(w_cum))

    # Per-run stats and filter short runs
    run_stats = (
        df.groupBy("run_id").agg(F.min("ts").alias(
            "start_ts"), F.sum("is_fail").alias("fails"))
    ).filter(F.col("fails") >= F.lit(min_fails))

    # Bucket runs by day and aggregate
    run_stats = run_stats.withColumn(
        "period", F.date_format(F.col("start_ts"), "yyyy-MM-dd"))
    agg = run_stats.groupBy("period").agg(F.count("run_id").alias(
        "outages"), F.sum("fails").alias("total_fails")).orderBy("period")

    for row in agg.collect():
        period = row["period"] if row["period"] is not None else "unknown"
        n = int(row["outages"] or 0)
        lost = int(row["total_fails"] or 0)
        outage_word = "outage" if n == 1 else "outages"
        print(f"{period}: {n} {outage_word}, {lost} packets lost", file=output)

    # Totals
    totals = df.agg(F.sum("is_success").alias("successes"),
                    F.sum("is_fail").alias("failures")).collect()[0]
    successes = int(totals["successes"] or 0)
    failures = int(totals["failures"] or 0)
    total = successes + failures
    if total:
        avail = successes / total * 100.0
        print(
            f"Total: {avail:.1f}% up ({successes} ok, {failures} lost)", file=output)

    spark.stop()


def main() -> None:
    p = argparse.ArgumentParser(
        description="Daily coarse outage report (Spark)")
    add_target_and_logfile_args(p)
    p.add_argument("min_fails", nargs="?", type=int, default=3,
                   help="Minimum consecutive failures to report")
    p.add_argument("--progress", action="store_true",
                   help="Show compact progress messages on stdout")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress progress messages")
    args = p.parse_args()

    logfile = args.logfile or f"./ping-{args.target}.log"
    if args.quiet:
        progress = None
    elif args.progress:
        progress = sys.stdout
    else:
        progress = sys.stderr

    daily_coarse_report(logfile, args.min_fails,
                        output=sys.stdout, progress=progress)


if __name__ == "__main__":
    main()
