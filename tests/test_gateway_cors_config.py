from __future__ import annotations

from services.gateway import main


def test_parse_single_configured_origin() -> None:
    origins = main._parse_cors_allowed_origins("https://frontend.example")
    assert origins == ["https://frontend.example"]


def test_parse_multiple_configured_origins() -> None:
    origins = main._parse_cors_allowed_origins("https://a.example,https://b.example")
    assert origins == ["https://a.example", "https://b.example"]


def test_parse_whitespace_and_empty_entries() -> None:
    origins = main._parse_cors_allowed_origins("  https://a.example  , , https://b.example  ,   ")
    assert origins == ["https://a.example", "https://b.example"]


def test_missing_environment_variable_results_in_empty_allowlist() -> None:
    options = main._build_cors_middleware_options(app_env="production", cors_allowed_origins_raw=None)
    assert options["allow_origins"] == []
    assert options["allow_credentials"] is True


def test_wildcard_is_neutralized_when_credentials_enabled() -> None:
    options = main._build_cors_middleware_options(
        app_env="development",
        cors_allowed_origins_raw="*,https://frontend.example",
    )
    assert options["allow_credentials"] is True
    assert "*" not in options["allow_origins"]
    assert options["allow_origins"] == ["https://frontend.example"]


def test_production_has_no_wildcard_fallback() -> None:
    options = main._build_cors_middleware_options(app_env="production", cors_allowed_origins_raw="")
    assert options["allow_origins"] == []
    assert options["allow_credentials"] is True
