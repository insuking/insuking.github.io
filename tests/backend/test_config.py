"""P43: `Settings.cors_extra_origins_list` parsing (see
backend/app/core/config.py and app/main.py's CORS middleware)."""

import pytest

from app.core.config import Settings

pytestmark = pytest.mark.P43


def test_cors_extra_origins_list_is_empty_by_default() -> None:
    assert Settings().cors_extra_origins_list == []


def test_cors_extra_origins_list_parses_a_single_origin() -> None:
    settings = Settings(cors_extra_origins="https://radar.example.com")
    assert settings.cors_extra_origins_list == ["https://radar.example.com"]


def test_cors_extra_origins_list_parses_multiple_origins_and_strips_whitespace() -> None:
    settings = Settings(cors_extra_origins="https://a.example.com, https://b.example.com ,, ")
    assert settings.cors_extra_origins_list == ["https://a.example.com", "https://b.example.com"]
