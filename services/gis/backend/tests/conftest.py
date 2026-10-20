"""Shared test configuration.

Unit tests need no database. They only require that settings can be constructed, so a placeholder
runtime password is provided when the environment has none (it is never used to connect).
Integration tests read real connection settings from the environment; see
``tests/integration/conftest.py``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("GIS_ENV", "test")
os.environ.setdefault("GIS_LOG_FORMAT", "console")
os.environ.setdefault("GIS_DB_APP_PASSWORD", "placeholder-not-used-by-unit-tests")

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
