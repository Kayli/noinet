#!/usr/bin/env python3
"""Report internet outage windows from a ping log produced by ping_inet.py."""

import argparse
import io
import os
import re
import sys
import time
from datetime import timedelta
from collections import OrderedDict
from typing import Iterable, Iterator, Optional, TextIO, TypedDict
import contextlib

from .shared import add_target_and_logfile_args


class Outage(TypedDict):
    """One continuous outage window detected in the log."""

    start: Optional[str]
    end: Optional[str]
    fails: int


class CoarseEntry(TypedDict):
    """Aggregated outage statistics for one coarse time bucket."""

    period: str   # e.g. "2026-04-15" (day) or "2026-04-15 10" (hour)
    outages: int  # number of distinct outage windows in this period
    total_fails: int  # total packets lost across all windows in this period


# Matches the leading timestamp written by ping_inet.py:  [2026-04-15 10:00:00]
_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")

# Patterns that indicate a lost packet (mirrors the awk script conditions)
_FAIL_RE = re.compile(
    r"no answer yet|Destination Host Unreachable|Network is unreachable|No route to host",
    re.IGNORECASE,
)

# Pattern that confirms a received packet
_SUCCESS_RE = re.compile(r"\d+ bytes from")


_GRANULARITIES = ("hour", "day")


def spark_coarse_report(logfile: str, min_fails: int = 3, granularity: str = "hour", output: TextIO = sys.stdout, progress: Optional[TextIO] = sys.stderr) -> None:
    """Compute coarse-grained outage summary using PySpark.

    This function delegates work to small, focused helpers to keep the
    implementation readable while preserving the same behaviour and
    progress messages.
    """
    # Local imports for Spark objects used in helpers
    try:
        from pyspark.sql import functions as F
        from pyspark.sql.window import Window
    except Exception as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "PySpark is not available in this environment: install pyspark and try again") from exc

    def _suppress_spark_output_cm():
        """Context manager to silence stdout/stderr while Spark starts."""
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
                "noinet-coarse-report").getOrCreate()
        try:
            spark.sparkContext.setLogLevel("ERROR")
        except Exception:
            pass
        return spark

    def _read_and_cache(spark):
        if progress:
            print("[spark] reading logfile into DataFrame...",
                  file=progress, flush=True)
        df = spark.read.text(logfile).withColumnRenamed("value", "line")
        df = df.cache()
        start = time.monotonic()
        try:
            total_lines = df.count()
        except Exception:
            total_lines = None
        elapsed = time.monotonic() - start
        if progress:
            if total_lines is not None:
                print(
                    f"[spark] cached {total_lines:,} lines in {elapsed:.1f}s", file=progress, flush=True)
            else:
                print(
                    f"[spark] cached (unknown line count) in {elapsed:.1f}s", file=progress, flush=True)
        return df

    def _prepare_columns(df):
        ts_re = _TS_RE.pattern
        df2 = df.withColumn(
            "ts_str", F.regexp_extract(F.col("line"), ts_re, 1))
        df2 = df2.withColumn("ts", F.to_timestamp(
            F.col("ts_str"), "yyyy-MM-dd HH:mm:ss"))
        df2 = df2.withColumn("is_fail", F.col(
            "line").rlike(_FAIL_RE.pattern).cast("int"))
        df2 = df2.withColumn("is_success", F.col(
            "line").rlike(_SUCCESS_RE.pattern).cast("int"))
        return df2

    def _compute_run_stats(df2):
        if progress:
            print("[spark] detecting failure runs (window ops)...",
                  file=progress, flush=True)
        w_order = Window.orderBy("ts")
        df3 = df2.withColumn("prev_fail", F.lag("is_fail").over(w_order))
        df3 = df3.withColumn("start_marker", F.when((F.col("is_fail") == 1) & (
            (F.col("prev_fail") == 0) | F.col("prev_fail").isNull()), 1).otherwise(0))

        w_cum = Window.orderBy("ts").rowsBetween(
            Window.unboundedPreceding, Window.currentRow)
        df3 = df3.withColumn("run_id", F.sum("start_marker").over(w_cum))

        if progress:
            print("[spark] computing per-run statistics and filtering short runs...",
                  file=progress, flush=True)

        run_stats = (
            df3.groupBy("run_id").agg(F.min("ts").alias(
                "start_ts"), F.sum("is_fail").alias("fails"))
        )
        run_stats = run_stats.filter(F.col("fails") >= F.lit(min_fails))
        return run_stats, df3

    def _aggregate_and_emit(run_stats):
        if granularity == "hour":
            period_fmt = "yyyy-MM-dd HH"
        else:
            period_fmt = "yyyy-MM-dd"
        run_stats2 = run_stats.withColumn("period", F.when(F.col("start_ts").isNull(
        ), F.lit("unknown")).otherwise(F.date_format(F.col("start_ts"), period_fmt)))
        agg = run_stats2.groupBy("period").agg(F.count("run_id").alias(
            "outages"), F.sum("fails").alias("total_fails")).orderBy("period")

        for row in agg.collect():
            period = row["period"] if row["period"] is not None else "unknown"
            n = int(row["outages"] or 0)
            lost = int(row["total_fails"] or 0)
            outage_word = "outage" if n == 1 else "outages"
            if period == "unknown":
                print(
                    f"{period}: {n} {outage_word}, {lost} packets lost", file=output)
            elif len(period) == 13:
                expected = 3600
                availability = max(0.0, (expected - lost) / expected * 100.0)
                print(
                    f"{period}: {n} {outage_word}, {lost} packets lost, {availability:.1f}% up", file=output)
            else:
                print(
                    f"{period}: {n} {outage_word}, {lost} packets lost", file=output)

    # Execute the refactored steps
    spark = _init_spark()
    df = _read_and_cache(spark)
    df2 = _prepare_columns(df)
    run_stats, df3 = _compute_run_stats(df2)
    _aggregate_and_emit(run_stats)

    # Totals
    totals = df3.agg(F.sum("is_success").alias("successes"),
                     F.sum("is_fail").alias("failures")).collect()[0]
    successes = int(totals["successes"] or 0)
    failures = int(totals["failures"] or 0)
    total = successes + failures
    if total:
        avail = successes / total * 100.0
        print(
            f"Total: {avail:.1f}% up ({successes} ok, {failures} lost)", file=output)

    spark.stop()


def spark_report(logfile: str, min_fails: int = 3, output: TextIO = sys.stdout, progress: Optional[TextIO] = sys.stderr) -> None:
    """Produce a detailed per-outage report using PySpark.

    Each outage line mirrors the old text format: ``start -> end (N packets lost)``
    or ``start -> (still down, N packets lost)`` when no recovery is present.
    """
    try:
        from pyspark.sql import SparkSession
        from pyspark.sql import functions as F
        from pyspark.sql.window import Window
    except Exception as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "PySpark is not available in this environment: install pyspark and try again") from exc

    # Silence Spark startup noise if requested
    with contextlib.contextmanager(_suppress_spark_output)():
        spark = SparkSession.builder.appName("noinet-report").getOrCreate()
    try:
        spark.sparkContext.setLogLevel("ERROR")
    except Exception:
        pass

    if progress:
        print("[spark] reading logfile into DataFrame...",
              file=progress, flush=True)
    df = spark.read.text(logfile).withColumnRenamed("value", "line")
    df = df.cache()
    try:
        total_lines = df.count()
    except Exception:
        total_lines = None
    if progress:
        if total_lines is not None:
            print(f"[spark] cached {total_lines:,} lines",
                  file=progress, flush=True)
        else:
            print("[spark] cached (unknown lines)", file=progress, flush=True)

    # Parse timestamps and flags
    ts_re = _TS_RE.pattern
    df = df.withColumn("ts_str", F.regexp_extract(F.col("line"), ts_re, 1))
    df = df.withColumn("ts", F.to_timestamp(
        F.col("ts_str"), "yyyy-MM-dd HH:mm:ss"))
    df = df.withColumn("is_fail", F.col(
        "line").rlike(_FAIL_RE.pattern).cast("int"))
    df = df.withColumn("is_success", F.col(
        "line").rlike(_SUCCESS_RE.pattern).cast("int"))

    # Detect run starts
    w_order = Window.orderBy("ts")
    df = df.withColumn("prev_fail", F.lag("is_fail").over(w_order))
    df = df.withColumn(
        "start_marker",
        F.when((F.col("is_fail") == 1) & ((F.col("prev_fail") == 0)
               | F.col("prev_fail").isNull()), 1).otherwise(0),
    )

    # Assign run ids and compute per-run fail counts
    w_cum = Window.orderBy("ts").rowsBetween(
        Window.unboundedPreceding, Window.currentRow)
    df = df.withColumn("run_id", F.sum("start_marker").over(w_cum))

    run_stats = (
        df.groupBy("run_id")
        .agg(
            F.min("ts").alias("start_ts"),
            F.sum("is_fail").alias("fails"),
        )
    )

    # For each start, find the first recovery timestamp after it
    df = df.withColumn("recovery_ts", F.when(
        F.col("is_success") == 1, F.col("ts")))
    w_follow = Window.orderBy("ts").rowsBetween(1, Window.unboundedFollowing)
    df = df.withColumn("first_recovery_after",
                       F.min("recovery_ts").over(w_follow))

    # Start rows mark the outage start timestamp
    start_rows = df.filter(F.col("start_marker") == 1).select(
        "run_id", F.col("ts").alias("start_ts"), "first_recovery_after")

    runs = start_rows.join(run_stats, on="run_id", how="left").filter(
        F.col("fails") >= F.lit(min_fails)).orderBy("start_ts")

    for row in runs.collect():
        start_ts = row["start_ts"]
        end_ts = row["first_recovery_after"]
        fails = int(row["fails"] or 0)
        start_s = start_ts.strftime(
            "%Y-%m-%d %H:%M:%S") if start_ts is not None else "unknown"
        if end_ts is None:
            print(f"{start_s} -> (still down, {fails} packets lost)", file=output)
        else:
            end_s = end_ts.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{start_s} -> {end_s} ({fails} packets lost)", file=output)

    spark.stop()


def report(
    lines: Iterable[str], min_fails: int = 3, output: TextIO = sys.stdout
) -> None:
    """Deprecated: kept for compatibility. Use Spark-based reporting instead.

    This function previously streamed lines and detected outages in pure
    Python. The project now uses PySpark for reporting; if you need to call
    from Python code with an iterable of lines, convert the iterable to a
    temporary file and use `spark_report`.
    """
    raise SystemExit(
        "report() is removed; use spark_report(logfile, ...) instead")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report internet outages from a ping log."
    )
    add_target_and_logfile_args(parser)
    parser.add_argument(
        "min_fails",
        nargs="?",
        type=int,
        default=3,
        help="Minimum consecutive failures to report (default: 3)",
    )
    parser.add_argument(
        "--coarse",
        metavar="GRANULARITY",
        choices=_GRANULARITIES,
        default=None,
        help="Print a coarse-grained summary bucketed by 'hour' or 'day' instead"
             " of listing every individual outage window.",
    )
    parser.add_argument(
        "--spark",
        action="store_true",
        default=True,
        help="Use PySpark for processing (default: true)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--progress", action="store_true",
                       help="Show progress messages on stdout")
    group.add_argument("--quiet", action="store_true",
                       help="Suppress progress messages entirely")
    args = parser.parse_args()
    logfile = args.logfile or f"./ping-{args.target}.log"
    # Determine where progress messages should go:
    if args.quiet:
        progress_stream = None
    elif args.progress:
        progress_stream = sys.stdout
    else:
        progress_stream = sys.stderr

    # Use Spark-based implementations for all reporting and aggregation.
    if args.coarse:
        spark_coarse_report(logfile, args.min_fails, args.coarse,
                            output=sys.stdout, progress=progress_stream)
    else:
        # For detailed reporting we currently rely on the Spark path too; if
        # implemented, pass the same progress stream.
        try:
            spark_report(logfile, args.min_fails,
                         output=sys.stdout, progress=progress_stream)
        except NameError:
            raise SystemExit(
                "Detailed Spark report not implemented; use --coarse")


if __name__ == "__main__":
    main()
