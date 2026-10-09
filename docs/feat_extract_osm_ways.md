# Extract OSM road ways

> subpackage `osm_road_weaver.extract`
> Extract ....

## Structure and dependencies
```
src/osm_road_weaver/extract/
├── __init__.py   # Public API
├── run.py        # QuackOSM extraction orchestration
├── regions.py    # Administrative boundary resolution
└── io.py         # Validation and write output
```

- `OSMnx` resolves a region name to an administrative boundary.
- `QuackOSM` downloads covering PBF extracts (or reads a local PBF) and selects ways with a `highway` tag.
- `DuckDB` filters and validates the results, then writes GeoParquet output.

## CLI
**Extracts PBF:**

```bash
uv run osm-road-weaver extract --region "<provine_name>" --output data/<provine_name>_ways_raw.parquet

# example:

uv run osm-road-weaver extract --region "Hà Nội" --output data/hanoi_ways_raw.parquet
```

**Use Local PBF:**

```bash
uv run osm-road-weaver extract \
  --region "Hà Nội" \
  --pbf data/vietnam.osm.pbf \
  --output data/hanoi_ways.parquet \
  --work-dir .cache/osm-road-weaver \
  --memory-limit 2GB \
  --threads 2
```

## Output schema
| Column | Type | Description |
| --- | --- | --- |
| `osm_way_id` | int64 | Unique original OSM way ID |
| `name` | string, nullable | First non-blank name/reference tag in priority order below |
| `highway` | string | Original highway classification |
| `bridge` | string, nullable | Original bridge tag, without boolean conversion |
| `geometry` | WKB | LineString, with explicit EPSG:4326 GeoParquet metadata |

- The output contains a single road-name field, `name`, using this fallback order:
    > `name` → `official_name` → `alt_name` → `name:vi` → `name:en` → `old_name` → `short_name` → `ref` → `int_ref` → `loc_name`.
- Missing, null, empty, and whitespace-only candidates are skipped. If no candidate is available, `name` is null. Selected values are preserved verbatim, including semicolons; the source name/reference tags are not exported as separate columns.
- Missing `bridge` tags remain null.
- Nodes, relations, Polygon and MultiLineString features are excluded.
- Closed road LineStrings, including roundabouts, are retained. 

> *No graph simplification, road-name matching, merging, or stroke reconstruction is performed at this stage.*

## Region selection and reruns

- Country defaults to Vietnam; use `--country` to change it. The CLI reports the resolved region name and OSM relation ID. Use `--relation-id` to select a specific administrative relation when a name is ambiguous.
- Boundaries reflect the OSM/Nominatim data at lookup time. QuackOSM 0.19 selects ways through nodes intersecting the boundary and keeps their full geometry. A segment crossing the region with no node inside can be omitted. Geometry is not clipped to the administrative boundary.
- First use requires network access for geocoding, PBF downloads, and the DuckDB spatial extension. A covering PBF may be much larger than the requested region. A local PBF must cover the entire region and include complete way nodes; the module cannot infer its coverage from the resulting road rows.
- The working directory caches boundary responses and QuackOSM conversions. `--refresh` bypasses boundary/conversion caches but does not guarantee a fresh provider PBF download. Use a new working directory or an immutable local PBF for a new source snapshot. Local PBF caches are keyed by SHA-256 content hash.
- Output metadata records the region identity, boundary hash, source path, local PBF hash when supplied, QuackOSM version, and OSM attribution.

CLI defaults can also be set through `OSM_COUNTRY`, `OSM_WORK_DIR`,
`OSM_EXTRACT_SOURCE`, `OSM_MEMORY_LIMIT`, and `OSM_THREADS`.

Library references: 
- [OSMnx geocoder](https://osmnx.readthedocs.io/en/stable/user-reference.html#module-osmnx.geocoder)
- [QuackOSM](https://kraina-ai.github.io/quackosm/latest/api/QuackOSM/).
- Source data: [© OpenStreetMap contributors, ODbL](https://www.openstreetmap.org/copyright).


### Explore extracted data

Open [`notebooks/explore_exteacted_osm_ways.ipynb`](notebooks/explore_exteacted_osm_ways.ipynb) in VS Code and select `.venv/bin/python` as the notebook kernel after installing the optional group:

    ```bash
    uv sync --group notebook
    ```

- Change `PARQUET_PATH` in the configuration cell or set `OSM_PARQUET_PATH` for load data need to explore.

- It shows metadata, sample rows, data-quality checks, name coverage, highway/bridge counts, Matplotlib charts, and an interactive Lonboard map with zoom/pan, hover tooltips, a click details panel, and a dropdown to switch between highway and name colors. `INTERACTIVE_MAP_LIMIT=None` renders all valid ways; set a positive limit (for example, 50,000) to use a reproducible sample and reduce RAM/GPU usage.

- Lonboard requires a Jupyter widget-capable frontend and WebGL. `USE_BASEMAP=False` disables background tiles; set it to `True` for the default online basemap.
- The DuckDB spatial extension must already be cached by extraction; set `OSM_DUCKDB_EXTENSION_DIR` for a custom cache location.
- The map uses longitude/latitude coordinates in EPSG:4326.



