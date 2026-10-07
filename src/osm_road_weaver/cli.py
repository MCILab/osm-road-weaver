"""Command-line entry point."""

import argparse
from importlib.metadata import version


def main() -> None:
    """Display package information and available commands."""
    parser = argparse.ArgumentParser(description=__package__)
    parser.add_argument("--version", action="version", version=version("osm-road-weaver"))
    parser.parse_args()
    parser.print_help()