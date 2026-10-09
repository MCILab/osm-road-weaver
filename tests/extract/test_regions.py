"""Boundary validation without Nominatim requests."""

from unittest.mock import Mock

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from osm_road_weaver.extract import regions


def frame(geometry=None, **fields):
    return gpd.GeoDataFrame(
        [
            {
                "osm_type": "relation",
                "type": "administrative",
                "osm_id": 123,
                "display_name": "Test region",
                **fields,
            }
        ],
        geometry=[box(105, 20, 106, 21) if geometry is None else geometry],
        crs=4326,
    )


@pytest.mark.parametrize("relation_id", [None, 123])
@pytest.mark.parametrize("refresh", [False, True])
def test_resolve_restores_settings(relation_id, refresh, monkeypatch, tmp_path):
    keys = ("cache_folder", "use_cache", "http_user_agent")
    previous = {key: getattr(regions.ox.settings, key) for key in keys}
    expected = frame()

    def geocode(query, **kwargs):
        assert query == ("R123" if relation_id else "Test, Vietnam")
        assert kwargs == {"by_osmid": relation_id is not None, "which_result": 1}
        assert regions.ox.settings.cache_folder == tmp_path
        assert regions.ox.settings.use_cache is not refresh
        assert "osm-road-weaver" in regions.ox.settings.http_user_agent
        return expected.to_crs(3857)

    monkeypatch.setattr(regions.ox, "geocode_to_gdf", geocode)
    result = regions.resolve_region(
        "Test", cache_directory=tmp_path, relation_id=relation_id, refresh=refresh
    )
    assert result.name == "Test region"
    assert result.osm_relation_id == 123
    assert result.geometry.equals_exact(expected.geometry.iloc[0], 1e-8)
    assert {key: getattr(regions.ox.settings, key) for key in keys} == previous


def test_geocoder_failure_restores_settings(monkeypatch, tmp_path):
    keys = ("cache_folder", "use_cache", "http_user_agent")
    previous = {key: getattr(regions.ox.settings, key) for key in keys}
    monkeypatch.setattr(regions.ox, "geocode_to_gdf", Mock(side_effect=RuntimeError("unavailable")))
    with pytest.raises(RuntimeError, match="unavailable"):
        regions.resolve_region("Test", cache_directory=tmp_path, refresh=True)
    assert {key: getattr(regions.ox.settings, key) for key in keys} == previous


@pytest.mark.parametrize(
    "kwargs", [{"query": " "}, {"country": "\t"}, {"relation_id": 0}, {"relation_id": -1}]
)
def test_invalid_arguments(kwargs, monkeypatch, tmp_path):
    geocode = Mock()
    monkeypatch.setattr(regions.ox, "geocode_to_gdf", geocode)
    with pytest.raises(ValueError):
        regions.resolve_region(**{"query": "Test", "cache_directory": tmp_path, **kwargs})
    geocode.assert_not_called()


@pytest.mark.parametrize(
    "result",
    [
        frame().iloc[:0],
        frame().loc[[0, 0]],
        frame(osm_type="way"),
        frame(type="city"),
        frame(Polygon()),
        frame(LineString([(105, 20), (106, 21)])),
    ],
)
def test_invalid_result(result, monkeypatch, tmp_path):
    monkeypatch.setattr(regions.ox, "geocode_to_gdf", Mock(return_value=result))
    with pytest.raises(ValueError):
        regions.resolve_region("Test", cache_directory=tmp_path)


@pytest.mark.parametrize(
    "geometry",
    [
        Polygon([(105, 20), (106, 21), (105, 21), (106, 20), (105, 20)]),
        MultiPolygon([box(105, 20, 106, 21), box(107, 20, 108, 21)]),
    ],
)
def test_validates_polygon(geometry, monkeypatch, tmp_path):
    monkeypatch.setattr(regions.ox, "geocode_to_gdf", Mock(return_value=frame(geometry)))
    result = regions.resolve_region("Test", cache_directory=tmp_path)
    assert result.geometry.is_valid
    assert not result.geometry.is_empty
    assert isinstance(result.geometry, Polygon | MultiPolygon)
