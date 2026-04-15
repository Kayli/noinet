#!/usr/bin/env python3
"""Monitor internet connectivity via ping, timestamping each output line."""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Iterator, TextIO, Generator, cast, Optional

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


def _list_system_interfaces() -> list[str]:
    # Try sysfs (Linux)
    try:
        if os.path.isdir("/sys/class/net"):
            return sorted(os.listdir("/sys/class/net"))
    except Exception:
        pass

    # Try `ip link` if available
    ip_cmd = shutil.which("ip")
    if ip_cmd:
        try:
            out = subprocess.check_output([ip_cmd, "link", "show"], text=True)
            names: list[str] = []
            for line in out.splitlines():
                m = re.match(r"^\d+:\s+([^:]+):", line)
                if m:
                    names.append(m.group(1))
            if names:
                return names
        except Exception:
            pass

    # Try ifconfig
    ifconf = shutil.which("ifconfig")
    if ifconf:
        try:
            out = subprocess.check_output([ifconf], text=True)
            names = []
            for line in out.splitlines():
                if line and not line.startswith(("\t", " ")):
                    m = re.match(r"^([\w.-]+)", line)
                    if m:
                        names.append(m.group(1))
            if names:
                return names
        except Exception:
            pass

    return []


def find_interface(kind: str) -> Optional[str]:
    """Return a real interface name for the requested kind ('wifi'|'lan'),
    or None if not found."""
    if kind not in ("wifi", "lan"):
        return None

    ifaces = _list_system_interfaces()
    # Prefer kernel wireless indicator when available
    if os.path.isdir("/sys/class/net"):
        for iface in ifaces:
            if iface == "lo":
                continue
            wireless_path = os.path.join("/sys/class/net", iface, "wireless")
            if kind == "wifi" and os.path.isdir(wireless_path):
                return iface

    # Heuristic name matching
    wifi_re = re.compile(r"^(wlan|wl|wlp|wifi)")
    lan_re = re.compile(r"^(eth|en|eno|ens|enp)")

    for iface in ifaces:
        if iface == "lo":
            continue
        if kind == "wifi" and wifi_re.match(iface):
            return iface
        if kind == "lan" and lan_re.match(iface):
            return iface

    # As a last resort: try iwconfig to detect wireless
    iw = shutil.which("iwconfig")
    if iw and kind == "wifi":
        for iface in ifaces:
            if iface == "lo":
                continue
            try:
                out = subprocess.check_output([iw, iface], text=True, stderr=subprocess.STDOUT)
                if "no wireless extensions" not in out.lower():
                    return iface
            except Exception:
                continue

    return None


def stream_ping(target: str, iface_name: Optional[str] = None) -> Iterator[str]:
    """Yield raw (un-timestamped) lines from a continuous ping process.

    Uses ``ping -O`` so failures like "no answer yet" are reported on every
    missing ICMP sequence number rather than silently dropped. If *iface_name*
    is provided, the ping command will be run bound to that interface.
    """
    ping_cmd = shutil.which("ping")
    if ping_cmd is None:
        raise SystemExit(
            "ping binary not found in PATH; install the system ping utility"
        )

    cmd = [ping_cmd, "-O", "-i", "1", "-n", target]
    if iface_name:
        cmd[1:1] = ["-I", iface_name]

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            yield line.rstrip("\n")


def run(target: str, logfile: str, output: TextIO = sys.stdout, iface_name: Optional[str] = None) -> None:
    """Timestamp every ping line and write it to *output* and *logfile*."""
    with open(logfile, "a", encoding="utf-8") as f:
        gen = stream_ping(target, iface_name=iface_name)
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
    # Determine which interface kind to use (wifi/lan) and map to a real
    # interface name when possible. If user provided --iface prefer that.
    selected_kind = args.iface
    if selected_kind is None:
        # prefer lan when available, otherwise wifi
        if find_interface("lan"):
            selected_kind = "lan"
        elif find_interface("wifi"):
            selected_kind = "wifi"
        else:
            selected_kind = "lan"

    iface_name = find_interface(selected_kind)
    logfile = args.logfile or f"./ping-{selected_kind}-{args.target}.log"
    run(args.target, logfile, iface_name=iface_name)


if __name__ == "__main__":
    main()
