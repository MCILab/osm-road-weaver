"""Extraction orchestration and one real-writer integration."""

import json
import shutil
from hashlib import sha256
from importlib.metadata import version
from unittest.mock import Mock

import pyarrow.parquet as pq
import pytest

from osm_road_weaver.extract import run


@pytest.fixture
def collaborators(monkeypatch, boundary, tmp_path):
    resolver = Mock(return_value=boundary)
    reader = Mock()
    source = tmp_path / "converted.parquet"
    reader.convert_geometry_to_parquet.return_value = source
    reader.convert_pbf_to_parquet.return_value = source
    factory = Mock(return_value=reader)
    writer = Mock(return_value=7)
    monkeypatch.setattr(run, "resolve_region", resolver)
    monkeypatch.setattr(run.quackosm, "PbfFileReader", factory)
    monkeypatch.setattr(run, "write_road_ways", writer)
    return resolver, factory, reader, writer


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("refresh", [False, True])
def test_options_and_provenance(local, refresh, collaborators, boundary, tmp_path):
    resolver, factory, reader, writer = collaborators
    pbf = tmp_path / "input.osm.pbf"
    pbf.write_bytes(b"synthetic snapshot")
    output = tmp_path / "out.geoparquet"
    work = tmp_path / "work"
    result = run.extract_ways(
        "Test",
        output,
        working_directory=work,
        pbf_path=pbf if local else None,
        country="Test country",
        relation_id=123,
        refresh=refresh,
        memory_limit="512MB",
        threads=1,
        extract_source="geofabrik",
    )
    resolver.assert_called_once_with(
        "Test",
        cache_directory=work / "nominatim",
        country="Test country",
        relation_id=123,
        refresh=refresh,
    )
    digest = sha256(pbf.read_bytes()).hexdigest() if local else None
    factory.assert_called_once_with(
        tags_filter={"highway": True},
        geometry_filter=boundary.geometry,
        custom_sql_filter="kind = 'way'",
        working_directory=work / "pbf" / digest if local else work / "pbf",
        osm_extract_source="geofabrik",
        allow_uncovered_geometry=False,
        cpu_limit=1,
        duckdb_conn_kwargs={
            "config_kwargs": {
                "extension_directory": str((work / "duckdb/extensions").resolve()),
                "memory_limit": "512MB",
                "threads": 1,
            }
        },
    )
    options = {"keep_all_tags": True, "explode_tags": False, "ignore_cache": refresh}
    if local:
        reader.convert_pbf_to_parquet.assert_called_once_with(pbf, **options)
        reader.convert_geometry_to_parquet.assert_not_called()
    else:
        reader.convert_geometry_to_parquet.assert_called_once_with(**options)
        reader.convert_pbf_to_parquet.assert_not_called()
    assert writer.call_args.args == (tmp_path / "converted.parquet", output)
    assert writer.call_args.kwargs["memory_limit"] == "512MB"
    assert writer.call_args.kwargs["threads"] == 1
    provenance = writer.call_args.kwargs["provenance"]
    assert provenance["source_pbf_sha256"] == digest
    assert provenance["source_pbf"] == (str(pbf) if local else None)
    assert provenance["boundary_sha256"] == sha256(boundary.geometry.wkb).hexdigest()
    assert provenance["quackosm_version"] == version("quackosm")
    assert provenance["osm_relation_id"] == 123
    assert provenance["region_name"] == boundary.name
    assert "no clipping or simplification" in provenance["boundary_behavior"]
    assert result == run.ExtractionResult(output, boundary.name, 123, 7)


def test_pbf_cache_tracks_content(collaborators, tmp_path):
    _, factory, _, _ = collaborators
    directories = []
    for index, content in enumerate([b"first", b"first", b"changed"]):
        pbf = tmp_path / f"{index}.pbf"
        pbf.write_bytes(content)
        run.extract_ways(
            "Test", tmp_path / "out.parquet", working_directory=tmp_path / "work", pbf_path=pbf
        )
        directories.append(factory.call_args.kwargs["working_directory"])
    assert directories[0] == directories[1]
    assert directories[1] != directories[2]


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"threads": 0}, ValueError),
        ({"output": "out.csv"}, ValueError),
        ({"pbf_path": "missing.pbf"}, FileNotFoundError),
    ],
)
def test_invalid_arguments(kwargs, error, collaborators, tmp_path):
    resolver, factory, _, writer = collaborators
    with pytest.raises(error):
        run.extract_ways(
            **{
                "region": "Test",
                "output": tmp_path / "out.parquet",
                "working_directory": tmp_path / "work",
                **kwargs,
            }
        )
    resolver.assert_not_called()
    factory.assert_not_called()
    writer.assert_not_called()


@pytest.mark.parametrize("stage", ["resolver", "converter", "writer"])
def test_failures_propagate(stage, collaborators, tmp_path):
    resolver, factory, reader, writer = collaborators
    target = {
        "resolver": resolver,
        "converter": reader.convert_geometry_to_parquet,
        "writer": writer,
    }[stage]
    target.side_effect = RuntimeError(stage)
    with pytest.raises(RuntimeError, match=stage):
        run.extract_ways("Test", tmp_path / "out.parquet", working_directory=tmp_path / "work")
    if stage == "resolver":
        factory.assert_not_called()
    if stage != "writer":
        writer.assert_not_called()


def test_real_writer(monkeypatch, boundary, source_factory, tmp_path, spatial_extensions):
    work = tmp_path / "work"
    shutil.copytree(spatial_extensions, work / "duckdb/extensions")
    monkeypatch.setattr(run, "resolve_region", Mock(return_value=boundary))
    reader = Mock()
    reader.convert_geometry_to_parquet.return_value = source_factory()
    monkeypatch.setattr(run.quackosm, "PbfFileReader", Mock(return_value=reader))
    output = tmp_path / "out.parquet"
    for _ in range(2):
        result = run.extract_ways("Test", str(output), working_directory=str(work))
        table = pq.read_table(result.path)
        assert result.way_count == table.num_rows == 1
        assert table["osm_way_id"].to_pylist() == [1]
        assert json.loads(table.schema.metadata[b"osm_road_weaver"])["osm_relation_id"] == 123
