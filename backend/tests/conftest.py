"""Shared pytest configuration."""

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def clear_cached_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
