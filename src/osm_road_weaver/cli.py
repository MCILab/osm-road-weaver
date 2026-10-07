"""Command-line entry point."""

import argparse
import os
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    """Run package commands."""
    parser = argparse.ArgumentParser(description=__package__)
    parser.add_argument("--version", action="version", version=version("osm-road-weaver"))

    commands = parser.add_subparsers(dest="command")

    # Extract regional highway ways to GeoParquet
    extract = commands.add_parser("extract", help="Extract regional highway ways to GeoParquet")
    extract.add_argument("--region", required=True, help="Administrative region name")
    extract.add_argument("--output", required=True, type=Path)
    extract.add_argument("--country", default=os.getenv("OSM_COUNTRY", "Vietnam"))
    extract.add_argument("--relation-id", type=int, help="Explicit OSM administrative relation ID")
    extract.add_argument("--pbf", type=Path, help="Use a local PBF instead of downloading extracts")
    extract.add_argument(
        "--work-dir", type=Path, default=Path(os.getenv("OSM_WORK_DIR", ".cache/osm-road-weaver"))
    )
    extract.add_argument("--extract-source", default=os.getenv("OSM_EXTRACT_SOURCE", "any"))
    extract.add_argument("--memory-limit", default=os.getenv("OSM_MEMORY_LIMIT", "2GB"))
    extract.add_argument("--threads", type=int, default=int(os.getenv("OSM_THREADS", "2")))
    extract.add_argument("--refresh", action="store_true", help="Recompute cached conversions")
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return

    from osm_road_weaver.extract import extract_ways

    result = extract_ways(
        args.region,
        args.output,
        working_directory=args.work_dir,
        country=args.country,
        relation_id=args.relation_id,
        pbf_path=args.pbf,
        extract_source=args.extract_source,
        refresh=args.refresh,
        memory_limit=args.memory_limit,
        threads=args.threads,
    )
    print(f"Region: {result.region_name} (relation/{result.osm_relation_id})")
    print(f"Wrote {result.way_count:,} ways to {result.path}")
