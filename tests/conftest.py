"""Small synthetic inputs; external services are forbidden in tests."""

import json
import os
import shutil
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely.geometry import LineString, box

from osm_road_weaver.extract.regions import Region


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture
def boundary() -> Region:
    return Region("Test region", 123, box(105, 20, 106, 21))


@pytest.fixture
def source_factory(tmp_path: Path) -> Callable[..., Path]:
    def create(rows: list[dict[str, Any]] | None = None, **metadata: Any) -> Path:
        if rows is None:
            rows = [
                {
                    "feature_id": "way/1",
                    "tags": {"highway": "residential"},
                    "geometry": LineString([(105, 20), (106, 21)]).wkb,
                }
            ]
        geo_column = {"encoding": "WKB", "geometry_types": ["LineString"], **metadata}
        schema = pa.schema(
            [
                ("feature_id", pa.string()),
                ("tags", pa.map_(pa.string(), pa.string())),
                ("geometry", pa.binary()),
            ],
            metadata={
                b"geo": json.dumps(
                    {
                        "version": "1.1.0",
                        "primary_column": "geometry",
                        "columns": {"geometry": geo_column},
                    }
                ).encode()
            },
        )
        path = tmp_path / f"source-{len(list(tmp_path.glob('source-*')))}.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
        return path

    return create


@pytest.fixture(scope="session")
def spatial_extensions(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Copy a preinstalled extension, never download from inside a test."""
    root = Path(os.environ.get("OSM_TEST_EXTENSION_DIRECTORY", Path.home() / ".duckdb/extensions"))
    target = tmp_path_factory.mktemp("spatial")
    with duckdb.connect() as connection:
        platform = connection.execute("PRAGMA platform").fetchone()[0]
    relative = Path(f"v{duckdb.__version__}") / platform / "spatial.duckdb_extension"
    source = root / relative
    if not source.is_file():
        pytest.fail(
            "Preinstall DuckDB spatial (INSTALL spatial), or set OSM_TEST_EXTENSION_DIRECTORY "
            f"to an extension root containing {relative}"
        )
    destination = target / relative
    destination.parent.mkdir(parents=True)
    shutil.copy2(source, destination)
    with duckdb.connect(config={"extension_directory": str(target)}) as connection:
        connection.load_extension("spatial")
    return target
