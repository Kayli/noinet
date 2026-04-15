"""Tests for ping_inet.py."""

import io
from pathlib import Path
from unittest.mock import patch

from ping_inet import format_line, run


class TestFormatLine:
    def test_basic_success_line(self) -> None:
        result = format_line("64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=9.5 ms", "2026-04-15 10:00:01")
        assert result == "[2026-04-15 10:00:01] 64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=9.5 ms"

    def test_failure_line(self) -> None:
        result = format_line("no answer yet for icmp_seq=2", "2026-04-15 10:00:02")
        assert result == "[2026-04-15 10:00:02] no answer yet for icmp_seq=2"

    def test_empty_line(self) -> None:
        result = format_line("", "2026-04-15 10:00:00")
        assert result == "[2026-04-15 10:00:00] "

    def test_timestamp_is_embedded_in_brackets(self) -> None:
        result = format_line("ping line", "2026-04-15 12:34:56")
        assert result.startswith("[2026-04-15 12:34:56]")


class TestRun:
    def test_output_is_timestamped(self, tmp_path: Path) -> None:
        logfile = str(tmp_path / "test.log")
        ping_lines = [
            "64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=9.5 ms",
            "no answer yet for icmp_seq=2",
        ]
        fixed_times = ["2026-04-15 10:00:01", "2026-04-15 10:00:02"]

        out = io.StringIO()
        with (
            patch("ping_inet.stream_ping", return_value=iter(ping_lines)),
            patch("ping_inet.timestamp", side_effect=fixed_times),
        ):
            run("8.8.8.8", logfile, output=out)

        lines = out.getvalue().splitlines()
        assert lines[0] == "[2026-04-15 10:00:01] 64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=9.5 ms"
        assert lines[1] == "[2026-04-15 10:00:02] no answer yet for icmp_seq=2"

    def test_logfile_matches_stdout(self, tmp_path: Path) -> None:
        logfile = str(tmp_path / "test.log")
        ping_lines = ["64 bytes from 1.1.1.1: icmp_seq=1 ttl=59 time=5.0 ms"]
        fixed_times = ["2026-04-15 09:00:00"]

        out = io.StringIO()
        with (
            patch("ping_inet.stream_ping", return_value=iter(ping_lines)),
            patch("ping_inet.timestamp", side_effect=fixed_times),
        ):
            run("1.1.1.1", logfile, output=out)

        with open(logfile) as f:
            log_lines = f.read().splitlines()

        assert log_lines == out.getvalue().splitlines()

    def test_logfile_is_appended(self, tmp_path: Path) -> None:
        logfile = str(tmp_path / "test.log")
        # Pre-seed the log file
        with open(logfile, "w") as f:
            f.write("[2026-04-15 09:59:59] existing line\n")

        ping_lines = ["64 bytes from 8.8.8.8: icmp_seq=1"]
        with (
            patch("ping_inet.stream_ping", return_value=iter(ping_lines)),
            patch("ping_inet.timestamp", return_value="2026-04-15 10:00:00"),
        ):
            run("8.8.8.8", logfile, output=io.StringIO())

        with open(logfile) as f:
            all_lines = f.read().splitlines()

        assert all_lines[0] == "[2026-04-15 09:59:59] existing line"
        assert all_lines[1] == "[2026-04-15 10:00:00] 64 bytes from 8.8.8.8: icmp_seq=1"

    def test_empty_ping_stream(self, tmp_path: Path) -> None:
        logfile = str(tmp_path / "empty.log")
        out = io.StringIO()
        with patch("ping_inet.stream_ping", return_value=iter([])):
            run("8.8.8.8", logfile, output=out)

        assert out.getvalue() == ""
        with open(logfile) as f:
            assert f.read() == ""
