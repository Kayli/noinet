#!/usr/bin/env python3
"""Report internet outage windows from a ping log produced by ping_inet.py."""

import argparse
import io
import os
import re
import sys
import time
from collections import OrderedDict
from typing import Iterable, Iterator, Optional, TextIO, TypedDict

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


_PROGRESS_INTERVAL = 0.25  # seconds between progress line refreshes


def _iter_with_progress(file: TextIO, progress: TextIO = sys.stderr) -> Iterator[str]:
    """Yield lines from *file* while printing a live progress indicator to *progress*.

    Progress is only emitted when *progress* is connected to a terminal, so
    piped or redirected output is never polluted.  Updates are rate-limited to
    at most one refresh per :data:`_PROGRESS_INTERVAL` seconds.
    """
    if not progress.isatty():
        yield from file
        return

    total = os.fstat(file.fileno()).st_size
    lines_read = 0
    next_update = time.monotonic()

    while True:
        line = file.readline()
        if not line:
            break
        yield line
        lines_read += 1
        now = time.monotonic()
        if now >= next_update:
            # Re-stat the file size so the progress percentage reflects a
            # growing logfile instead of capping at the initial size.
            try:
                current_total = os.fstat(file.fileno()).st_size
            except OSError:
                current_total = total
            pct = min(file.tell() * 100 // current_total,
                      100) if current_total else 0
            print(
                f"\r  reading \u2026 {lines_read:,} lines ({pct}%)",
                end="", file=progress, flush=True,
            )
            next_update = now + _PROGRESS_INTERVAL

    # Overwrite the progress line with a compact completion notice.
    print(
        f"\r  read {lines_read:,} lines \u2014 done.{' ' * 20}",
        file=progress, flush=True,
    )


def parse_timestamp(line: str) -> Optional[str]:
    """Extract the timestamp string from a log line, or return None."""
    m = _TS_RE.match(line)
    return m.group(1) if m else None


def is_failure(line: str) -> bool:
    """Return True if the line reports a missing/unreachable packet."""
    return bool(_FAIL_RE.search(line))


def is_success(line: str) -> bool:
    """Return True if the line reports a successfully received packet."""
    return bool(_SUCCESS_RE.search(line))


def parse_outages(lines: Iterable[str], min_fails: int = 3) -> Iterator[Outage]:
    """Yield outage dicts for every gap that lasted at least *min_fails* packets.

    Each dict has:
      ``start``  – timestamp of the first lost packet
      ``end``    – timestamp of the first recovered packet, or ``None`` if the
                   log ends while still down
      ``fails``  – total number of lost packets in the window
    """
    current_ts: Optional[str] = None
    fails: int = 0
    outage_start: Optional[str] = None

    for line in lines:
        ts = parse_timestamp(line)
        if ts:
            current_ts = ts

        if is_failure(line):
            fails += 1
            if fails == 1:
                outage_start = current_ts
        elif is_success(line):
            if fails >= min_fails:
                yield {"start": outage_start, "end": current_ts, "fails": fails}
            fails = 0
            outage_start = None

    if fails >= min_fails:
        yield {"start": outage_start, "end": None, "fails": fails}


def format_outage(outage: Outage) -> str:
    """Format an outage dict as a human-readable string."""
    start = outage["start"]
    end = outage["end"]
    fails = outage["fails"]
    if end is None:
        return f"{start} -> (still down, {fails} packets lost)"
    return f"{start} -> {end} ({fails} packets lost)"


_GRANULARITIES = ("hour", "day")


def _period_key(ts: Optional[str], granularity: str) -> str:
    """Truncate a timestamp string to the requested granularity bucket.

    * ``"hour"`` keeps ``YYYY-MM-DD HH`` (drops minutes and seconds).
    * ``"day"``  keeps ``YYYY-MM-DD``.

    A ``None`` timestamp (outage started before any timestamped line) is
    returned as the string ``"unknown"``.
    """
    if ts is None:
        return "unknown"
    if granularity == "day":
        return ts[:10]   # "YYYY-MM-DD"
    # default: "hour"
    return ts[:13]       # "YYYY-MM-DD HH"


def aggregate_by_period(
    outages: Iterable[Outage], granularity: str = "hour"
) -> Iterator[CoarseEntry]:
    """Group *outages* into coarse time buckets and yield one :class:`CoarseEntry`
    per bucket in chronological order.

    :param granularity: ``"hour"`` (default) or ``"day"``.
    """
    if granularity not in _GRANULARITIES:
        raise ValueError(
            f"granularity must be one of {_GRANULARITIES!r}, got {granularity!r}"
        )
    buckets: OrderedDict[str, CoarseEntry] = OrderedDict()
    for outage in outages:
        key = _period_key(outage["start"], granularity)
        if key not in buckets:
            buckets[key] = CoarseEntry(period=key, outages=0, total_fails=0)
        buckets[key]["outages"] += 1
        buckets[key]["total_fails"] += outage["fails"]
    yield from buckets.values()


def format_coarse_entry(entry: CoarseEntry) -> str:
    """Format a :class:`CoarseEntry` as a human-readable summary line."""
    period = entry["period"]
    n = entry["outages"]
    lost = entry["total_fails"]
    outage_word = "outage" if n == 1 else "outages"
    # Assume the monitor runs continuously: an "hour" bucket represents
    # 3600 expected pings. We report a percentage for hour buckets only;
    # daily summaries do not include a percentage.
    if period == "unknown":
        return f"{period}: {n} {outage_word}, {lost} packets lost"
    if len(period) == 13:  # "YYYY-MM-DD HH"
        expected = 3600
        availability = max(0.0, (expected - lost) / expected * 100.0)
        return f"{period}: {n} {outage_word}, {lost} packets lost, {availability:.1f}% up"
    # day or other formats: no percentage
    return f"{period}: {n} {outage_word}, {lost} packets lost"


def coarse_report(
    lines: Iterable[str],
    min_fails: int = 3,
    granularity: str = "hour",
    output: TextIO = sys.stdout,
) -> None:
    """Write a coarse-grained outage summary to *output*.

    Outages are first detected with :func:`parse_outages`, then bucketed by
    *granularity* (``"hour"`` or ``"day"``).  Each bucket is printed as a
    single summary line.
    """
    # Stream the input so we don't materialize a large log in memory.
    counts = {"successes": 0, "failures": 0}

    def counting_lines(src: Iterable[str]) -> Iterator[str]:
        for L in src:
            if is_success(L):
                counts["successes"] += 1
            if is_failure(L):
                counts["failures"] += 1
            yield L

    for entry in aggregate_by_period(parse_outages(counting_lines(lines), min_fails), granularity):
        print(format_coarse_entry(entry), file=output)

    total = counts["successes"] + counts["failures"]
    if total:
        avail = counts["successes"] / total * 100.0
        print(
            f"Total: {avail:.1f}% up ({counts['successes']} ok, {counts['failures']} lost)", file=output)


def report(
    lines: Iterable[str], min_fails: int = 3, output: TextIO = sys.stdout
) -> None:
    """Write a formatted outage report to *output*."""
    for outage in parse_outages(lines, min_fails):
        print(format_outage(outage), file=output)


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
    args = parser.parse_args()
    logfile = args.logfile or f"./ping-{args.target}.log"
    buf = io.StringIO()
    with open(logfile, encoding="utf-8") as f:
        lines: Iterable[str] = _iter_with_progress(f)
        if args.coarse:
            coarse_report(lines, args.min_fails, args.coarse, output=buf)
        else:
            report(lines, args.min_fails, output=buf)
    sys.stdout.write(buf.getvalue())


if __name__ == "__main__":
    main()
