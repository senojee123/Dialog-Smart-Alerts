"""Pipeline tests: they need the ``pipeline`` extra (GeoPandas, pyogrio) and GDAL's command-line tools.

Without them the tests in this directory are not collected, and the report header says why; set
``GIS_REQUIRE_PIPELINE=1`` (as the ``pipeline`` Docker target does) to make their absence a failure.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

import pytest

MISSING = [
    *(name for name in ("geopandas", "pyogrio", "pandas") if importlib.util.find_spec(name) is None),
    *(tool for tool in ("ogr2ogr", "ogrinfo") if shutil.which(tool) is None),
]

if MISSING:
    if os.environ.get("GIS_REQUIRE_PIPELINE") == "1":
        raise RuntimeError(f"pipeline tests required but {', '.join(MISSING)} missing")
    collect_ignore_glob = ["test_*.py"]


def pytest_report_header() -> str | None:
    if MISSING:
        return f"pipeline tests not collected: {', '.join(MISSING)} missing (pip install -e '.[pipeline]')"
    return None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.pipeline)
