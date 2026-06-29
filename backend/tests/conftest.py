"""Shared pytest configuration."""

import pytest

from app.core.config import get_settings
from app.modules.chat.service import get_chat_model


@pytest.fixture(autouse=True)
def clear_cached_settings_and_chat_model():
    get_chat_model.cache_clear()
    get_settings.cache_clear()
    yield
    get_chat_model.cache_clear()
    get_settings.cache_clear()
