"""CLI parsing and forwarding without external extraction."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from osm_road_weaver import cli, extract


@pytest.mark.parametrize("override", [False, True])
def test_extract_options(override, monkeypatch, tmp_path, capsys):
    output = tmp_path / "out.parquet"
    work = tmp_path / "cache"
    pbf = tmp_path / "input.pbf"
    for key, value in {
        "OSM_COUNTRY": "Laos",
        "OSM_WORK_DIR": str(work),
        "OSM_EXTRACT_SOURCE": "geofabrik",
        "OSM_MEMORY_LIMIT": "512MB",
        "OSM_THREADS": "1",
    }.items():
        monkeypatch.setenv(key, value)
    command = [
        "osm-road-weaver",
        "extract",
        "--region",
        "Test",
        "--output",
        str(output),
        "--pbf",
        str(pbf),
        "--relation-id",
        "123",
        "--refresh",
    ]
    if override:
        command += [
            "--country",
            "Vietnam",
            "--threads",
            "3",
            "--memory-limit",
            "1GB",
            "--extract-source",
            "any",
            "--work-dir",
            str(tmp_path),
        ]
    monkeypatch.setattr(sys, "argv", command)
    runner = Mock(return_value=extract.ExtractionResult(output, "Test region", 123, 1234))
    monkeypatch.setattr(extract, "extract_ways", runner)
    cli.main()
    runner.assert_called_once_with(
        "Test",
        output,
        working_directory=tmp_path if override else work,
        country="Vietnam" if override else "Laos",
        relation_id=123,
        pbf_path=pbf,
        extract_source="any" if override else "geofabrik",
        refresh=True,
        memory_limit="1GB" if override else "512MB",
        threads=3 if override else 1,
    )
    text = capsys.readouterr().out
    assert "Test region (relation/123)" in text
    assert f"Wrote 1,234 ways to {output}" in text


@pytest.mark.parametrize(
    "args", [["extract"], ["extract", "--region", "Test"], ["extract", "--output", "out.parquet"]]
)
def test_required_arguments(args, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["osm-road-weaver", *args])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("option", ["--help", "--version"])
def test_installed_entrypoint(option):
    executable = Path(sys.executable).parent / "osm-road-weaver"
    result = subprocess.run([str(executable), option], capture_output=True, text=True, check=True)
    assert result.stdout.strip()
    if option == "--help":
        assert "extract" in result.stdout
