"""Shared helpers for the package.

Keep common argument definitions in one place so modules stay DRY.
"""
import argparse


def add_target_and_logfile_args(
    parser: argparse.ArgumentParser, default_target: str = "8.8.8.8"
) -> None:
    parser.add_argument(
        "target",
        nargs="?",
        default=default_target,
        help=f"Target IP or hostname (default: {default_target})",
    )
    parser.add_argument(
        "--logfile",
        help="Log file path (default: ./ping-<target>.log)",
    )
