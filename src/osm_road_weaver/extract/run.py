"""Extract original highway ways for a named region into GeoParquet."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import file_digest, sha256
from importlib.metadata import version
from pathlib import Path

import quackosm

from osm_road_weaver.extract.io import write_road_ways
from osm_road_weaver.extract.regions import resolve_region


@dataclass(frozen=True)
class ExtractionResult:
    """Location, region identity, and validated row count of an extraction."""

    path: Path
    region_name: str
    osm_relation_id: int
    way_count: int


def extract_ways(
    region: str,
    output: str | Path,
    *,
    working_directory: str | Path,
    country: str = "Vietnam",
    relation_id: int | None = None,
    pbf_path: str | Path | None = None,
    extract_source: str = "any",
    refresh: bool = False,
    memory_limit: str = "2GB",
    threads: int = 2,
) -> ExtractionResult:
    """Extract regional highway LineString ways without clipping or simplification.

    Cached boundary/PBF conversion results are reused by default. For reproducible
    source snapshots, supply an immutable local PBF and retain the working directory.
    """
    if threads < 1:
        raise ValueError("threads must be positive")
    
    output, working_directory = Path(output), Path(working_directory)
    if output.suffix not in {".parquet", ".geoparquet"}:
        raise ValueError("Output must have a .parquet or .geoparquet extension")
    
    if pbf_path is not None and not Path(pbf_path).is_file():
        raise FileNotFoundError(f"Local PBF does not exist: {pbf_path}")
    
    working_directory.mkdir(parents=True, exist_ok=True)

    boundary = resolve_region(
        region,
        cache_directory=working_directory / "nominatim",
        country=country,
        relation_id=relation_id,
        refresh=refresh,
    )

    pbf_digest = None
    pbf_directory = working_directory / "pbf"

    if pbf_path is not None:
        with Path(pbf_path).open("rb") as source_file:
            pbf_digest = file_digest(source_file, "sha256").hexdigest()
        pbf_directory /= pbf_digest
    
    extension_directory = working_directory / "duckdb" / "extensions"
    
    reader = quackosm.PbfFileReader(
        tags_filter={"highway": True},
        geometry_filter=boundary.geometry,
        custom_sql_filter="kind = 'way'",
        working_directory=pbf_directory,
        osm_extract_source=extract_source,
        allow_uncovered_geometry=False,
        cpu_limit=threads,
        duckdb_conn_kwargs={
            "config_kwargs": {
                "extension_directory": str(extension_directory.resolve()),
                "memory_limit": memory_limit,
                "threads": threads,
            }
        },
    )
    
    options = {"keep_all_tags": True, "explode_tags": False, "ignore_cache": refresh}

    if pbf_path is None:
        source = reader.convert_geometry_to_parquet(**options)
    else:
        source = reader.convert_pbf_to_parquet(Path(pbf_path), **options)
    
    count = write_road_ways(
        Path(source),
        output,
        extension_directory=extension_directory,
        memory_limit=memory_limit,
        threads=threads,
        provenance={
            "region_query": region,
            "region_name": boundary.name,
            "osm_relation_id": boundary.osm_relation_id,
            "source_parquet": str(source),
            "source_pbf": str(pbf_path) if pbf_path is not None else None,
            "source_pbf_sha256": pbf_digest,
            "boundary_sha256": sha256(boundary.geometry.wkb).hexdigest(),
            "quackosm_version": version("quackosm"),
            "attribution": "© OpenStreetMap contributors; ODbL 1.0",
            "boundary_behavior": "QuackOSM node-based selection; no clipping or simplification",
        },
    )
    return ExtractionResult(output, boundary.name, boundary.osm_relation_id, count)
