"""Resolve administrative region boundaries with OSMnx."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import osmnx as ox
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon

_SETTINGS_LOCK = Lock()


@dataclass(frozen=True)
class Region:
    """An administrative OSM relation and its EPSG:4326 boundary."""

    name: str
    osm_relation_id: int
    geometry: Polygon | MultiPolygon

    
def resolve_region(
    query: str,
    *,
    cache_directory: Path,
    country: str = "Vietnam",
    relation_id: int | None = None,
    refresh: bool = False,
) -> Region:
    """Resolve the first matching administrative relation, or an explicit relation ID.

    OSMnx handles Nominatim caching and request pacing. Settings are restored after
    the call; calls through this module are serialized because OSMnx settings are global.
    """
    if not query.strip() or not country.strip():
        raise ValueError("Region and country must not be blank")

    if relation_id is not None and relation_id <= 0:
        raise ValueError("OSM relation ID must be positive")

    settings = {
        "cache_folder": cache_directory,
        "use_cache": not refresh,
        "http_user_agent": "osm-road-weaver/0.1 (OSMnx regional road extraction)",
    }
    with _SETTINGS_LOCK:
        previous = {key: getattr(ox.settings, key) for key in settings}
        try:
            for key, value in settings.items():
                setattr(ox.settings, key, value)
            frame = ox.geocode_to_gdf(
                f"R{relation_id}" if relation_id is not None else f"{query}, {country}",
                by_osmid=relation_id is not None,
                which_result=1,
            )
        finally:
            for key, value in previous.items():
                setattr(ox.settings, key, value)

    if len(frame) != 1:
        raise ValueError("Expected exactly one administrative region")

    row = frame.to_crs("EPSG:4326").iloc[0]

    if row.get("osm_type") != "relation" or row.get("type") != "administrative":
        raise ValueError("Result is not an administrative relation; specify --relation-id")

    geometry = make_valid(row.geometry)

    if not isinstance(geometry, Polygon | MultiPolygon) or geometry.is_empty:
        raise ValueError("Region must have a non-empty Polygon or MultiPolygon boundary")
    return Region(str(row["display_name"]), int(row["osm_id"]), geometry)
