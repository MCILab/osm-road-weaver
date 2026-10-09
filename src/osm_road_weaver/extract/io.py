"""Validate and project QuackOSM output using DuckDB and Arrow batches."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import CRS

NAME_TAGS = (
    "name",
    "official_name",
    "alt_name",
    "name:vi",
    "name:en",
    "old_name",
    "short_name",
    "ref",
    "int_ref",
    "loc_name",
)
ROAD_TAGS = ("name", "highway", "bridge", "junction")


def write_road_ways(
    source: Path,
    output: Path,
    *,
    extension_directory: Path,
    memory_limit: str = "2GB",
    threads: int = 2,
    provenance: dict[str, Any] | None = None,
) -> int:
    """Write unique, valid LineString ways to GeoParquet, replacing output atomically.

    Source must be compact-tag QuackOSM GeoParquet in WGS84. Polygon features and
    non-way elements are excluded, while invalid LineStrings fail validation.
    """
    source, output = Path(source), Path(output)

    if source.resolve() == output.resolve():
        raise ValueError("Source and output must be different paths")
    
    if threads < 1:
        raise ValueError("threads must be positive")
    
    if pq.read_metadata(source).num_rows == 0:
        raise ValueError("No highway LineString ways found for this region/source")
    
    schema = pq.read_schema(source)
    if not {"feature_id", "tags", "geometry"}.issubset(schema.names):
        raise ValueError("Expected QuackOSM columns: feature_id, tags, geometry")
    
    if not pa.types.is_map(schema.field("tags").type):
        raise ValueError("Expected compact tags as an Arrow map")
    
    geo = json.loads((schema.metadata or {}).get(b"geo", b"{}"))
    geometry_metadata = geo.get("columns", {}).get("geometry", {})
    if geometry_metadata.get("encoding") != "WKB":
        raise ValueError("Source must use GeoParquet WKB encoding")
    
    source_crs = geometry_metadata.get("crs", "OGC:CRS84")
    if source_crs is None or not CRS(source_crs).equals(CRS(4326), ignore_axis_order=True):
        raise ValueError("Source CRS must be WGS84 (EPSG:4326 or OGC:CRS84)")
    
    output.parent.mkdir(parents=True, exist_ok=True)
    extension_directory.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=output.parent, prefix=".osm-ways-") as temporary:
        temporary_path = Path(temporary)
        with duckdb.connect(
            str(temporary_path / "validation.duckdb"),
            config={
                "extension_directory": str(extension_directory.resolve()),
                "memory_limit": memory_limit,
                "threads": threads,
            },
        ) as connection:
            connection.install_extension("spatial")
            connection.load_extension("spatial")
            connection.execute("SET enable_geoparquet_conversion = false")
            connection.read_parquet(str(source)).create_view("raw_features")

            if connection.execute(
                "SELECT count(*) FROM raw_features WHERE feature_id IS NULL"
            ).fetchone()[0]:
                raise ValueError("Source contains null OSM feature IDs")
            
            connection.execute("""
                CREATE TABLE candidate_ways AS
                SELECT feature_id, tags, ST_GeomFromWKB(geometry) AS geometry
                FROM raw_features
                WHERE starts_with(feature_id, 'way/') AND tags['highway'] IS NOT NULL
            """)

            invalid = connection.execute("""
                SELECT count(*) FROM candidate_ways
                WHERE NOT regexp_full_match(feature_id, 'way/[1-9][0-9]*')
                   OR geometry IS NULL OR trim(tags['highway']) = ''
            """).fetchone()[0]

            if invalid:
                raise ValueError(
                    f"Found {invalid} ways with invalid IDs, geometry, or highway tags"
                )
            
            connection.execute("""
                CREATE TABLE road_ways AS
                SELECT * FROM candidate_ways
                WHERE ST_GeometryType(geometry) = 'LINESTRING'
            """)

            count, unique_count, invalid = connection.execute("""
                SELECT count(*), count(DISTINCT feature_id), count(*) FILTER (
                    WHERE NOT ST_IsValid(geometry) OR ST_IsEmpty(geometry)
                       OR NOT isfinite(ST_XMin(geometry)) OR NOT isfinite(ST_YMin(geometry))
                       OR NOT isfinite(ST_XMax(geometry)) OR NOT isfinite(ST_YMax(geometry))
                       OR ST_XMin(geometry) < -180 OR ST_XMax(geometry) > 180
                       OR ST_YMin(geometry) < -90 OR ST_YMax(geometry) > 90
                ) FROM road_ways
            """).fetchone()

            if not count:
                raise ValueError("No highway LineString ways found for this region/source")
            
            if count != unique_count:
                raise ValueError("Duplicate OSM way IDs found")
            
            if invalid:
                raise ValueError(f"Found {invalid} invalid LineString geometries")
            
            # Ignore missing/whitespace-only names without modifying selected tag values.
            name_candidates = ", ".join(
                rf"CASE WHEN NOT regexp_full_match(tags['{tag}'], '\s*') "
                f"THEN tags['{tag}'] END"
                for tag in NAME_TAGS
            )

            projection = ", ".join(
                f"COALESCE({name_candidates}) AS name"
                if tag == "name"
                else f"tags['{tag}'] AS {tag}"
                for tag in ROAD_TAGS
            )

            reader = connection.sql(f"""
                SELECT CAST(split_part(feature_id, '/', 2) AS BIGINT) AS osm_way_id,
                       {projection}, CAST(ST_AsWKB(geometry) AS BLOB) AS geometry
                FROM road_ways
            """).to_arrow_reader(batch_size=100_000)

            metadata = {
                "version": "1.1.0",
                "primary_column": "geometry",
                "columns": {
                    "geometry": {
                        "encoding": "WKB",
                        "geometry_types": ["LineString"],
                        "crs": CRS(4326).to_json_dict(),
                    }
                },
            }
            output_schema = reader.schema.with_metadata(
                {
                    b"geo": json.dumps(metadata).encode(),
                    b"osm_road_weaver": json.dumps(provenance or {}, ensure_ascii=False).encode(),
                }
            )
            staged = temporary_path / "ways.parquet"

            with pq.ParquetWriter(staged, output_schema, compression="zstd") as writer:
                for batch in reader:
                    writer.write_batch(batch)
            if pq.read_metadata(staged).num_rows != count:
                raise ValueError("Output row count does not match validated input")
            
            staged.replace(output)
    
    return count
