"""Exercise real SQL validation and GeoParquet serialization."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pyproj import CRS
from shapely.geometry import LineString, Point, box

from osm_road_weaver.extract import io

LINE = LineString([(105, 20), (106, 21)]).wkb


def row(feature_id="way/1", geometry=LINE, **tags):
    return {
        "feature_id": feature_id,
        "geometry": geometry,
        "tags": {"highway": "residential", **tags},
    }


def test_filter_schema_metadata_and_rerun(source_factory, tmp_path, spatial_extensions):
    source = source_factory(
        [
            row(name="Đường A", bridge="yes", junction="roundabout"),
            row("way/2", name=" \t", official_name=" Đường B ", alt_name="Other"),
            row("node/3", Point(105, 20).wkb),
            row("relation/4"),
            row("way/5", box(105, 20, 106, 21).wkb),
            row("way/6", highway=None),
        ]
    )
    output = tmp_path / "nested" / "ways.parquet"
    for _ in range(2):
        assert (
            io.write_road_ways(
                source,
                output,
                extension_directory=spatial_extensions,
                provenance={"region": "Hà Nội"},
            )
            == 2
        )
        table = pq.read_table(output).sort_by("osm_way_id")
        assert table.column_names == [
            "osm_way_id",
            "name",
            "highway",
            "bridge",
            "junction",
            "geometry",
        ]
        assert table.schema.field("osm_way_id").type == pa.int64()
        assert table.to_pylist() == [
            {
                "osm_way_id": 1,
                "name": "Đường A",
                "highway": "residential",
                "bridge": "yes",
                "junction": "roundabout",
                "geometry": LINE,
            },
            {
                "osm_way_id": 2,
                "name": " Đường B ",
                "highway": "residential",
                "bridge": None,
                "junction": None,
                "geometry": LINE,
            },
        ]
        metadata = table.schema.metadata
        geo = json.loads(metadata[b"geo"])
        assert geo["primary_column"] == "geometry"
        assert geo["columns"]["geometry"]["encoding"] == "WKB"
        assert geo["columns"]["geometry"]["geometry_types"] == ["LineString"]
        assert CRS(geo["columns"]["geometry"]["crs"]).equals(CRS(4326))
        assert json.loads(metadata[b"osm_road_weaver"]) == {"region": "Hà Nội"}
    assert not list(output.parent.glob(".osm-ways-*"))


@pytest.mark.parametrize(
    "tag",
    [
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
    ],
)
def test_name_fallback(tag, source_factory, tmp_path, spatial_extensions):
    tags = dict.fromkeys(io.NAME_TAGS, " \t\n")
    tags[tag] = " Đường thử "
    # Later candidates must not override the first nonblank name.
    for later in io.NAME_TAGS[io.NAME_TAGS.index(tag) + 1 :]:
        tags[later] = "Later name"
    source = source_factory([row(**tags), row("way/2")])
    output = tmp_path / "out.parquet"
    io.write_road_ways(source, output, extension_directory=spatial_extensions)
    assert pq.read_table(output).sort_by("osm_way_id")["name"].to_pylist() == [" Đường thử ", None]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "No highway"),
        ([row(None)], "null OSM"),
        ([row("way/0")], "invalid IDs"),
        ([row("way/abc")], "invalid IDs"),
        ([row(geometry=None)], "invalid IDs"),
        ([row(highway="  ")], "invalid IDs"),
        ([row(), row()], "Duplicate"),
        ([row(geometry=LineString().wkb)], "invalid LineString"),
        ([row(geometry=LineString([(105, 20), (105, 20)]).wkb)], "invalid LineString"),
        ([row(geometry=LineString([(181, 20), (182, 21)]).wkb)], "invalid LineString"),
        ([row(geometry=LineString([(105, -91), (106, -92)]).wkb)], "invalid LineString"),
        ([row(geometry=LineString([(105, 20), (float("inf"), 21)]).wkb)], "invalid LineString"),
        ([row("node/1")], "No highway"),
    ],
)
def test_invalid_data_preserves_output(rows, message, source_factory, tmp_path, spatial_extensions):
    source = source_factory(rows)
    output = tmp_path / "out.parquet"
    output.write_bytes(b"previous output")
    with pytest.raises(ValueError, match=message):
        io.write_road_ways(source, output, extension_directory=spatial_extensions)
    assert output.read_bytes() == b"previous output"
    assert not list(tmp_path.glob(".osm-ways-*"))


@pytest.mark.parametrize("crs", ["EPSG:4326", "OGC:CRS84"])
def test_wgs84_crs(crs, source_factory, tmp_path, spatial_extensions):
    assert (
        io.write_road_ways(
            source_factory(crs=CRS(crs).to_json_dict()),
            tmp_path / "out.parquet",
            extension_directory=spatial_extensions,
        )
        == 1
    )


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"crs": None}, "CRS"),
        ({"crs": CRS(3857).to_json_dict()}, "CRS"),
        ({"encoding": "point"}, "WKB"),
    ],
)
def test_invalid_metadata(metadata, message, source_factory, tmp_path):
    with pytest.raises(ValueError, match=message):
        io.write_road_ways(
            source_factory(**metadata),
            tmp_path / "out.parquet",
            extension_directory=tmp_path / "extensions",
        )


@pytest.mark.parametrize("change", ["missing_column", "wrong_tags", "missing_geo"])
def test_invalid_schema(change, source_factory, tmp_path):
    source = source_factory()
    table = pq.read_table(source)
    if change == "missing_column":
        table = table.drop(["feature_id"])
        message = "Expected QuackOSM columns"
    elif change == "wrong_tags":
        table = table.set_column(1, "tags", pa.array(["highway=residential"]))
        message = "Arrow map"
    else:
        table = table.replace_schema_metadata({})
        message = "WKB"
    pq.write_table(table, source)
    with pytest.raises(ValueError, match=message):
        io.write_road_ways(
            source, tmp_path / "out.parquet", extension_directory=tmp_path / "extensions"
        )


def test_early_validation(source_factory, tmp_path):
    source = source_factory()
    with pytest.raises(ValueError, match="different paths"):
        io.write_road_ways(source, source, extension_directory=tmp_path)
    with pytest.raises(ValueError, match="threads"):
        io.write_road_ways(
            source, tmp_path / "out.parquet", threads=0, extension_directory=tmp_path
        )


def test_write_failure_preserves_output(source_factory, tmp_path, spatial_extensions, monkeypatch):
    source = source_factory()
    output = tmp_path / "out.parquet"
    output.write_bytes(b"old")

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pq.ParquetWriter, "write_batch", fail_write)
    with pytest.raises(OSError, match="disk full"):
        io.write_road_ways(source, output, extension_directory=spatial_extensions)
    assert output.read_bytes() == b"old"
    assert not list(tmp_path.glob(".osm-ways-*"))


def test_row_count_mismatch_preserves_output(
    source_factory, tmp_path, spatial_extensions, monkeypatch
):
    source = source_factory()
    output = tmp_path / "out.parquet"
    output.write_bytes(b"old")
    original = pq.read_metadata

    def wrong_staged_count(path, *args, **kwargs):
        from types import SimpleNamespace

        if path.name == "ways.parquet":
            return SimpleNamespace(num_rows=0)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pq, "read_metadata", wrong_staged_count)
    with pytest.raises(ValueError, match="row count"):
        io.write_road_ways(source, output, extension_directory=spatial_extensions)
    assert output.read_bytes() == b"old"
    assert not list(tmp_path.glob(".osm-ways-*"))
