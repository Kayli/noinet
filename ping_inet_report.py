#!/usr/bin/env python3
"""Report internet outage windows from a ping log produced by ping_inet.py."""

import argparse
import re
import sys
from typing import Iterable, Iterator, Optional, TextIO, TypedDict


class Outage(TypedDict):
    """One continuous outage window detected in the log."""

    start: Optional[str]
    end: Optional[str]
    fails: int


# Matches the leading timestamp written by ping_inet.py:  [2026-04-15 10:00:00]
_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")

# Patterns that indicate a lost packet (mirrors the awk script conditions)
_FAIL_RE = re.compile(
    r"no answer yet|Destination Host Unreachable|Network is unreachable|No route to host",
    re.IGNORECASE,
)

# Pattern that confirms a received packet
_SUCCESS_RE = re.compile(r"\d+ bytes from")


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
    parser.add_argument(
        "target",
        nargs="?",
        default="8.8.8.8",
        help="Target used when naming the default log file (default: 8.8.8.8)",
    )
    parser.add_argument(
        "min_fails",
        nargs="?",
        type=int,
        default=3,
        help="Minimum consecutive failures to report (default: 3)",
    )
    parser.add_argument(
        "--logfile",
        help="Log file path (default: ./ping-<target>.log)",
    )
    args = parser.parse_args()
    logfile = args.logfile or f"./ping-{args.target}.log"
    with open(logfile) as f:
        report(f, args.min_fails)


if __name__ == "__main__":
    main()
