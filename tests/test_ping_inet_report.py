"""Tests for ping_inet_report.py."""

import io

import pytest

from noinet.ping_inet_report import (
    CoarseEntry,
    aggregate_by_period,
    coarse_report,
    format_coarse_entry,
    format_outage,
    is_failure,
    is_success,
    parse_outages,
    parse_timestamp,
    report,
    Outage,
)


class TestParseTimestamp:
    def test_valid_timestamp(self) -> None:
        line = "[2026-04-15 10:00:01] 64 bytes from 8.8.8.8: icmp_seq=1"
        assert parse_timestamp(line) == "2026-04-15 10:00:01"

    def test_midnight_timestamp(self) -> None:
        line = "[2026-01-01 00:00:00] no answer yet for icmp_seq=1"
        assert parse_timestamp(line) == "2026-01-01 00:00:00"

    def test_no_timestamp_returns_none(self) -> None:
        assert parse_timestamp("64 bytes from 8.8.8.8") is None

    def test_empty_line_returns_none(self) -> None:
        assert parse_timestamp("") is None

    def test_partial_bracket_returns_none(self) -> None:
        assert parse_timestamp(
            "[2026-04-15 10:00:01 missing close bracket") is None


class TestIsFailure:
    @pytest.mark.parametrize(
        "line",
        [
            "[2026-04-15 10:00:02] no answer yet for icmp_seq=2",
            "[2026-04-15 10:00:03] From 192.168.1.1 icmp_seq=3 Destination Host Unreachable",
            "[2026-04-15 10:00:04] Network is unreachable",
            "[2026-04-15 10:00:05] connect: No route to host",
            # Case-insensitive
            "[2026-04-15 10:00:06] NETWORK IS UNREACHABLE",
        ],
    )
    def test_known_failure_patterns(self, line: str) -> None:
        assert is_failure(line) is True

    @pytest.mark.parametrize(
        "line",
        [
            "[2026-04-15 10:00:01] 64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=9.5 ms",
            "[2026-04-15 10:00:00] PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.",
            "",
        ],
    )
    def test_non_failure_lines(self, line: str) -> None:
        assert is_failure(line) is False


class TestIsSuccess:
    @pytest.mark.parametrize(
        "line",
        [
            "[2026-04-15 10:00:01] 64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=9.5 ms",
            "[2026-04-15 10:00:01] 1234 bytes from 1.1.1.1: icmp_seq=1",
        ],
    )
    def test_known_success_patterns(self, line: str) -> None:
        assert is_success(line) is True

    @pytest.mark.parametrize(
        "line",
        [
            "[2026-04-15 10:00:02] no answer yet for icmp_seq=2",
            "[2026-04-15 10:00:00] PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.",
            "",
        ],
    )
    def test_non_success_lines(self, line: str) -> None:
        assert is_success(line) is False


def _make_log(*entries: tuple[str, str]) -> list[str]:
    """Build a list of timestamped log lines from (timestamp, content) pairs."""
    return [f"[{ts}] {content}" for ts, content in entries]


class TestParseOutages:
    def test_no_failures_yields_nothing(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "64 bytes from 8.8.8.8: icmp_seq=2"),
        )
        assert not list(parse_outages(lines, min_fails=3))

    def test_fewer_fails_than_threshold_yields_nothing(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "64 bytes from 8.8.8.8: icmp_seq=4"),
        )
        assert not list(parse_outages(lines, min_fails=3))

    def test_single_outage_exactly_at_threshold(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "no answer yet for icmp_seq=4"),
            ("2026-04-15 10:00:05", "64 bytes from 8.8.8.8: icmp_seq=5"),
        )
        outages = list(parse_outages(lines, min_fails=3))
        assert len(outages) == 1
        assert outages[0] == Outage(
            start="2026-04-15 10:00:02", end="2026-04-15 10:00:05", fails=3
        )

    def test_single_outage_above_threshold(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "no answer yet for icmp_seq=4"),
            ("2026-04-15 10:00:05", "no answer yet for icmp_seq=5"),
            ("2026-04-15 10:00:06", "64 bytes from 8.8.8.8: icmp_seq=6"),
        )
        outages = list(parse_outages(lines, min_fails=3))
        assert len(outages) == 1
        assert outages[0]["fails"] == 4

    def test_still_down_at_eof(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "no answer yet for icmp_seq=4"),
        )
        outages = list(parse_outages(lines, min_fails=3))
        assert len(outages) == 1
        assert outages[0] == Outage(
            start="2026-04-15 10:00:02", end=None, fails=3)

    def test_multiple_separate_outages(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "no answer yet for icmp_seq=4"),
            ("2026-04-15 10:00:05", "64 bytes from 8.8.8.8: icmp_seq=5"),
            ("2026-04-15 10:01:01", "64 bytes from 8.8.8.8: icmp_seq=61"),
            ("2026-04-15 10:01:02", "Network is unreachable"),
            ("2026-04-15 10:01:03", "Network is unreachable"),
            ("2026-04-15 10:01:04", "Network is unreachable"),
            ("2026-04-15 10:01:05", "Network is unreachable"),
            ("2026-04-15 10:01:06", "64 bytes from 8.8.8.8: icmp_seq=66"),
        )
        outages = list(parse_outages(lines, min_fails=3))
        assert len(outages) == 2
        assert outages[0] == Outage(
            start="2026-04-15 10:00:02", end="2026-04-15 10:00:05", fails=3
        )
        assert outages[1] == Outage(
            start="2026-04-15 10:01:02", end="2026-04-15 10:01:06", fails=4
        )

    def test_mixed_failure_types(self) -> None:
        """Different failure messages in one window should all be counted."""
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "Destination Host Unreachable"),
            ("2026-04-15 10:00:04", "Network is unreachable"),
            ("2026-04-15 10:00:05", "64 bytes from 8.8.8.8: icmp_seq=5"),
        )
        outages = list(parse_outages(lines, min_fails=3))
        assert len(outages) == 1
        assert outages[0]["fails"] == 3

    def test_empty_log(self) -> None:
        assert not list(parse_outages([], min_fails=3))

    def test_min_fails_one(self) -> None:
        """min_fails=1 should report every single lost packet."""
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "64 bytes from 8.8.8.8: icmp_seq=3"),
        )
        outages = list(parse_outages(lines, min_fails=1))
        assert len(outages) == 1
        assert outages[0]["fails"] == 1


class TestFormatOutage:
    def test_resolved_outage(self) -> None:
        outage = Outage(
            start="2026-04-15 10:00:02", end="2026-04-15 10:00:05", fails=3
        )
        assert format_outage(outage) == (
            "2026-04-15 10:00:02 -> 2026-04-15 10:00:05 (3 packets lost)"
        )

    def test_still_down(self) -> None:
        outage = Outage(
            start="2026-04-15 10:00:02", end=None, fails=5
        )
        assert format_outage(outage) == (
            "2026-04-15 10:00:02 -> (still down, 5 packets lost)"
        )

    def test_single_packet_lost(self) -> None:
        outage = Outage(
            start="2026-04-15 10:00:02", end="2026-04-15 10:00:03", fails=1
        )
        assert format_outage(outage) == (
            "2026-04-15 10:00:02 -> 2026-04-15 10:00:03 (1 packets lost)"
        )


class TestReport:
    def test_single_outage(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "no answer yet for icmp_seq=4"),
            ("2026-04-15 10:00:05", "64 bytes from 8.8.8.8: icmp_seq=5"),
        )
        out = io.StringIO()
        report(lines, min_fails=3, output=out)
        assert out.getvalue().strip() == (
            "2026-04-15 10:00:02 -> 2026-04-15 10:00:05 (3 packets lost)"
        )

    def test_no_outages_produces_no_output(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
        )
        out = io.StringIO()
        report(lines, min_fails=3, output=out)
        assert out.getvalue() == ""

    def test_empty_input(self) -> None:
        out = io.StringIO()
        report([], min_fails=3, output=out)
        assert out.getvalue() == ""

    def test_two_outages_two_lines(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "no answer yet for icmp_seq=4"),
            ("2026-04-15 10:00:05", "64 bytes from 8.8.8.8: icmp_seq=5"),
            ("2026-04-15 10:01:01", "no answer yet for icmp_seq=61"),
            ("2026-04-15 10:01:02", "no answer yet for icmp_seq=62"),
            ("2026-04-15 10:01:03", "no answer yet for icmp_seq=63"),
            ("2026-04-15 10:01:04", "64 bytes from 8.8.8.8: icmp_seq=64"),
        )
        out = io.StringIO()
        report(lines, min_fails=3, output=out)
        result_lines = out.getvalue().strip().splitlines()
        assert len(result_lines) == 2
        assert "10:00:02" in result_lines[0]
        assert "10:01:01" in result_lines[1]


# ---------------------------------------------------------------------------
# Coarse-grained report tests
# ---------------------------------------------------------------------------

def _outages(*specs: tuple[str, str, int]) -> list[Outage]:
    """Build a list of Outage dicts from (start, end, fails) triples."""
    return [Outage(start=s, end=e, fails=f) for s, e, f in specs]


class TestAggregate:
    def test_no_outages_yields_nothing(self) -> None:
        assert not list(aggregate_by_period([], granularity="hour"))
        assert not list(aggregate_by_period([], granularity="day"))

    def test_single_outage_hour_bucket(self) -> None:
        outages = _outages(("2026-04-15 10:00:02", "2026-04-15 10:00:05", 3))
        entries = list(aggregate_by_period(outages, granularity="hour"))
        assert len(entries) == 1
        assert entries[0] == CoarseEntry(
            period="2026-04-15 10", outages=1, total_fails=3)

    def test_single_outage_day_bucket(self) -> None:
        outages = _outages(("2026-04-15 10:00:02", "2026-04-15 10:00:05", 3))
        entries = list(aggregate_by_period(outages, granularity="day"))
        assert len(entries) == 1
        assert entries[0] == CoarseEntry(
            period="2026-04-15", outages=1, total_fails=3)

    def test_two_outages_same_hour(self) -> None:
        outages = _outages(
            ("2026-04-15 10:00:02", "2026-04-15 10:00:05", 3),
            ("2026-04-15 10:05:00", "2026-04-15 10:05:10", 5),
        )
        entries = list(aggregate_by_period(outages, granularity="hour"))
        assert len(entries) == 1
        assert entries[0]["outages"] == 2
        assert entries[0]["total_fails"] == 8

    def test_two_outages_different_hours(self) -> None:
        outages = _outages(
            ("2026-04-15 10:00:02", "2026-04-15 10:00:05", 3),
            ("2026-04-15 11:00:02", "2026-04-15 11:00:06", 4),
        )
        entries = list(aggregate_by_period(outages, granularity="hour"))
        assert len(entries) == 2
        assert entries[0] == CoarseEntry(
            period="2026-04-15 10", outages=1, total_fails=3)
        assert entries[1] == CoarseEntry(
            period="2026-04-15 11", outages=1, total_fails=4)

    def test_two_outages_same_day_different_hours_collapse_to_one_day(self) -> None:
        outages = _outages(
            ("2026-04-15 10:00:02", "2026-04-15 10:00:05", 3),
            ("2026-04-15 23:00:00", "2026-04-15 23:00:30", 7),
        )
        entries = list(aggregate_by_period(outages, granularity="day"))
        assert len(entries) == 1
        assert entries[0]["outages"] == 2
        assert entries[0]["total_fails"] == 10

    def test_outages_across_two_days(self) -> None:
        outages = _outages(
            ("2026-04-14 23:00:00", "2026-04-14 23:00:10", 4),
            ("2026-04-15 01:00:00", "2026-04-15 01:00:05", 3),
        )
        entries = list(aggregate_by_period(outages, granularity="day"))
        assert len(entries) == 2
        assert entries[0]["period"] == "2026-04-14"
        assert entries[1]["period"] == "2026-04-15"

    def test_unknown_timestamp_when_start_is_none(self) -> None:
        outages = [Outage(start=None, end="2026-04-15 10:00:05", fails=3)]
        entries = list(aggregate_by_period(outages, granularity="hour"))
        assert len(entries) == 1
        assert entries[0]["period"] == "unknown"

    def test_invalid_granularity_raises(self) -> None:
        with pytest.raises(ValueError, match="granularity"):
            list(aggregate_by_period([], granularity="minute"))

    def test_chronological_order_preserved(self) -> None:
        outages = _outages(
            ("2026-04-15 08:00:00", "2026-04-15 08:00:10", 3),
            ("2026-04-15 09:00:00", "2026-04-15 09:00:10", 5),
            ("2026-04-15 08:30:00", "2026-04-15 08:30:10", 4),  # back to hour 08
        )
        entries = list(aggregate_by_period(outages, granularity="hour"))
        # insertion order: 08 first, then 09; the late entry for 08 merges in
        assert entries[0]["period"] == "2026-04-15 08"
        assert entries[0]["outages"] == 2
        assert entries[0]["total_fails"] == 7
        assert entries[1]["period"] == "2026-04-15 09"


class TestFormatCoarseEntry:
    def test_single_outage(self) -> None:
        entry = CoarseEntry(period="2026-04-15 10", outages=1, total_fails=5)
        assert format_coarse_entry(
            entry) == "2026-04-15 10: 1 outage, 5 packets lost, 99.9% up"

    def test_plural_outages(self) -> None:
        entry = CoarseEntry(period="2026-04-15", outages=3, total_fails=12)
        assert format_coarse_entry(
            entry) == "2026-04-15: 3 outages, 12 packets lost"

    def test_unknown_period(self) -> None:
        entry = CoarseEntry(period="unknown", outages=1, total_fails=3)
        assert "unknown" in format_coarse_entry(entry)


class TestCoarseReport:
    def test_coarse_report_hour_output(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "no answer yet for icmp_seq=4"),
            ("2026-04-15 10:00:05", "64 bytes from 8.8.8.8: icmp_seq=5"),
            ("2026-04-15 11:00:01", "no answer yet for icmp_seq=61"),
            ("2026-04-15 11:00:02", "no answer yet for icmp_seq=62"),
            ("2026-04-15 11:00:03", "no answer yet for icmp_seq=63"),
            ("2026-04-15 11:00:04", "64 bytes from 8.8.8.8: icmp_seq=64"),
        )
        out = io.StringIO()
        coarse_report(lines, min_fails=3, granularity="hour", output=out)
        result_lines = out.getvalue().strip().splitlines()
        assert len(result_lines) == 3
        assert result_lines[0] == "2026-04-15 10: 1 outage, 3 packets lost, 99.9% up"
        assert result_lines[1] == "2026-04-15 11: 1 outage, 3 packets lost, 99.9% up"
        assert result_lines[2] == "Total: 33.3% up (3 ok, 6 lost), 0:00:06 down"

    def test_coarse_report_day_merges_hours(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
            ("2026-04-15 10:00:02", "no answer yet for icmp_seq=2"),
            ("2026-04-15 10:00:03", "no answer yet for icmp_seq=3"),
            ("2026-04-15 10:00:04", "no answer yet for icmp_seq=4"),
            ("2026-04-15 10:00:05", "64 bytes from 8.8.8.8: icmp_seq=5"),
            ("2026-04-15 11:00:01", "no answer yet for icmp_seq=61"),
            ("2026-04-15 11:00:02", "no answer yet for icmp_seq=62"),
            ("2026-04-15 11:00:03", "no answer yet for icmp_seq=63"),
            ("2026-04-15 11:00:04", "64 bytes from 8.8.8.8: icmp_seq=64"),
        )
        out = io.StringIO()
        coarse_report(lines, min_fails=3, granularity="day", output=out)
        result_lines = out.getvalue().strip().splitlines()
        assert len(result_lines) == 2
        assert result_lines[0] == "2026-04-15: 2 outages, 6 packets lost"
        assert result_lines[1] == "Total: 33.3% up (3 ok, 6 lost), 0:00:06 down"

    def test_coarse_report_no_outages_produces_no_output(self) -> None:
        lines = _make_log(
            ("2026-04-15 10:00:01", "64 bytes from 8.8.8.8: icmp_seq=1"),
        )
        out = io.StringIO()
        coarse_report(lines, min_fails=3, granularity="hour", output=out)
        assert out.getvalue() == "Total: 100.0% up (1 ok, 0 lost), 0:00:00 down\n"
