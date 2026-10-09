# Tests

This directory contains the project's test suite, organized by feature or component.

## 1. Common setup and commands

Run commands from the project root. Synchronize the environment with `uv.lock`:

```bash
uv sync --locked
```

Complete any group-specific setup below before running that group or the full suite.

```bash
# Check lint rules
uv run ruff check .

# Run all test groups
uv run pytest

# Run a specific group or file
uv run pytest tests/extract/
uv run pytest tests/test_cli.py
```

Shared fixtures live in `tests/conftest.py`. The current suite blocks Python socket
connections to prevent unintended network calls. Test data and generated outputs
use pytest temporary directories.

## 2. Extraction tests

Location: `tests/extract/`.

### 2.1 Setup

Install DuckDB Spatial before running the extraction group or the full suite:

```bash
uv run python -c 'import duckdb; c = duckdb.connect(); c.install_extension("spatial"); c.close()'
```

- The extension installation is a one-time setup per DuckDB version/platform and may require network access. 
- Tests copy the installed Spatial binary into a temporary
directory; they do not download extensions. 
- The default source is `~/.duckdb/extensions`. Set `OSM_TEST_EXTENSION_DIRECTORY` to use another extension
root containing `v<duckdb-version>/<platform>/spatial.duckdb_extension`. 
- Missing or
incompatible extensions fail explicitly rather than skipping SQL tests.

### 2.2 Scope and limitations

- Fixtures generate small GeoParquet inputs.
- Nominatim and QuackOSM conversion calls are mocked. 
- Writer tests execute real DuckDB Spatial SQL and Arrow/Parquet I/O.
- The orchestration integration test uses a synthetic converter output and the real writer. 
- These tests do not validate live geocoding, actual PBF decoding/downloads,
or performance on large extracts.
