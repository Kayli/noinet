#!/usr/bin/env python3
"""Monitor internet connectivity via ping, timestamping each output line."""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Iterator, TextIO, Generator, cast

from .shared import add_target_and_logfile_args


def timestamp() -> str:
    """Return the current wall-clock time formatted for the log."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_line(line: str, ts: str) -> str:
    """Prepend a bracketed timestamp to a ping output line."""
    return f"[{ts}] {line}"


def stream_ping(target: str) -> Iterator[str]:
    """Yield raw (un-timestamped) lines from a continuous ping process.

    Uses ``ping -O`` so failures like "no answer yet" are reported on every
    missing ICMP sequence number rather than silently dropped.
    """
    ping_cmd = shutil.which("ping")
    if ping_cmd is None:
        raise SystemExit(
            "ping binary not found in PATH; install the system ping utility"
        )

    with subprocess.Popen(
        [ping_cmd, "-O", "-i", "1", "-n", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            yield line.rstrip("\n")


def run(target: str, logfile: str, output: TextIO = sys.stdout) -> None:
    """Timestamp every ping line and write it to *output* and *logfile*."""
    with open(logfile, "a", encoding="utf-8") as f:
        gen = stream_ping(target)
        try:
            for line in gen:
                ts = timestamp()
                formatted = format_line(line, ts)
                print(formatted, file=output, flush=True)
                print(formatted, file=f, flush=True)
        except KeyboardInterrupt:
            try:
                g = cast(Generator[str, None, None], gen)
                g.close()
            except (RuntimeError, GeneratorExit):
                pass
            # Exit cleanly on Ctrl+C without a traceback
            return


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor internet connectivity via ping."
    )
    add_target_and_logfile_args(parser)
    args = parser.parse_args()
    logfile = args.logfile or f"./ping-{args.target}.log"
    run(args.target, logfile)


if __name__ == "__main__":
    main()
