from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import (
    DEFAULT_ALEMBIC_CONFIG,
    DEFAULT_SERVICE_AREA_BBOX,
    DbRole,
    DbSslMode,
    Environment,
    Settings,
)


def make(**overrides: object) -> Settings:
    values: dict[str, object] = {"db_app_password": "app-secret"}
    values.update(overrides)
    return Settings.model_validate(values)


def test_defaults_are_safe_and_point_at_repository_files() -> None:
    settings = make()
    assert settings.service_area_bbox == DEFAULT_SERVICE_AREA_BBOX
    assert settings.db_ssl_mode is DbSslMode.DISABLE
    assert settings.postgis_min_version_tuple == (3, 6)
    assert DEFAULT_ALEMBIC_CONFIG.is_file(), "db/alembic.ini must exist at the repository root"


def test_default_service_area_contains_epsg5235_area_of_use() -> None:
    # EPSG registry area of use for EPSG:5235: lon 79.64..81.95, lat 5.86..9.88.
    min_lon, min_lat, max_lon, max_lat = DEFAULT_SERVICE_AREA_BBOX
    assert min_lon < 79.64
    assert min_lat < 5.86
    assert max_lon > 81.95
    assert max_lat > 9.88


def test_environment_variables_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIS_SERVICE_AREA_BBOX", "79.5, 5.9, 82.0, 9.9")
    monkeypatch.setenv("GIS_CORS_ALLOW_ORIGINS", "http://localhost:5173, https://ops.example.lk")
    monkeypatch.setenv("GIS_DB_PORT", "6543")
    settings = Settings()
    assert settings.service_area_bbox == (79.5, 5.9, 82.0, 9.9)
    assert settings.cors_allow_origins == ["http://localhost:5173", "https://ops.example.lk"]
    assert settings.db_port == 6543


def test_empty_cors_variable_means_no_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIS_CORS_ALLOW_ORIGINS", "")
    assert Settings().cors_allow_origins == []


@pytest.mark.parametrize(
    "bbox",
    [
        "79,5,78,10",
        "79,11,82,10",
        "79,5,82",
        "a,b,c,d",
        "-181,5,82,10",
        "79.0,5.66,82.15,10.08",  # wider than the envelope the database accepts
    ],
)
def test_invalid_service_area_is_rejected(monkeypatch: pytest.MonkeyPatch, bbox: str) -> None:
    monkeypatch.setenv("GIS_SERVICE_AREA_BBOX", bbox)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("name", ["GisApp", "gis-app", "1gis", "gis app", "x" * 64, "gis;drop"])
def test_database_identifiers_are_validated(name: str) -> None:
    with pytest.raises(ValidationError):
        make(db_app_user=name)


def test_postgis_version_format_is_validated() -> None:
    with pytest.raises(ValidationError):
        make(postgis_min_version="3")


def test_root_path_format_is_validated() -> None:
    assert make(api_root_path="/gis").api_root_path == "/gis"
    with pytest.raises(ValidationError):
        make(api_root_path="gis/")


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        make(env=Environment.PRODUCTION, db_ssl_mode="require", cors_allow_origins=["*"])


def test_production_requires_database_tls_unless_explicitly_waived() -> None:
    with pytest.raises(ValidationError, match="SSL"):
        make(env=Environment.PRODUCTION)
    waived = make(env=Environment.PRODUCTION, db_allow_insecure_transport=True)
    assert waived.env is Environment.PRODUCTION


def test_production_requires_separate_runtime_and_migration_logins() -> None:
    with pytest.raises(ValidationError, match="differ"):
        make(env=Environment.PRODUCTION, db_ssl_mode="verify-full", db_migrator_user="gis_app")


def test_database_url_escapes_special_characters() -> None:
    password = "p@ss:w/rd%'"
    settings = make(db_app_password=password, db_host="db.internal", db_name="gis_test")
    url = settings.database_url(DbRole.APP)
    parsed = make_url(url.render_as_string(hide_password=False))
    assert parsed.password == password
    assert parsed.username == "gis_app"
    assert parsed.drivername == "postgresql+asyncpg"
    assert password not in repr(settings), "secrets must not appear in reprs"


def test_migrator_url_requires_a_password() -> None:
    with pytest.raises(ValueError, match="MIGRATOR_PASSWORD"):
        make(db_migrator_password=None).database_url(DbRole.MIGRATOR)
    url = make(db_migrator_password="mig").database_url(DbRole.MIGRATOR)
    assert url.username == "gis_migrator"


def test_app_url_requires_a_password() -> None:
    settings = Settings.model_validate({"db_app_password": None})
    with pytest.raises(ValueError, match="APP_PASSWORD"):
        settings.database_url()


# --- tenant, exports and enrichment -------------------------------------------------------------------


def test_requests_act_for_the_platforms_organisation_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (make().tenant_id, make().tenant_name) == ("dialog-smart-alerts", "Dialog Smart Alerts")
    monkeypatch.setenv("GIS_TENANT_ID", "wildlife-dept")
    assert Settings().tenant_id == "wildlife-dept"


@pytest.mark.parametrize("tenant", ["Dialog", "a", "has space", "-leading", "x" * 64])
def test_the_tenant_id_is_validated(tenant: str) -> None:
    with pytest.raises(ValidationError, match="tenant_id"):
        make(tenant_id=tenant)


def test_production_needs_no_authentication_settings() -> None:
    """The main platform owns sign-in: production starts without any identity provider."""
    assert make(env=Environment.PRODUCTION, db_ssl_mode="require").env is Environment.PRODUCTION


def test_export_limit_is_bounded() -> None:
    with pytest.raises(ValidationError, match="greater than or equal"):
        make(export_max_features=0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"enrichment_settlement_radius_m": 0},
        {"enrichment_road_radius_m": 100_001},
        {"enrichment_device_radius_m": -5},
        {"enrichment_device_limit": 51},
        {"max_request_body_bytes": 10},
    ],
)
def test_enrichment_limits_are_bounded(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make(**overrides)


def test_database_errors_never_carry_bound_parameters() -> None:
    """Parameters include searched positions; an error message or log line must not (docs/security.md)."""
    from app.db.engine import create_engine

    engine = create_engine(make(db_host="db.internal"))
    assert engine.sync_engine.hide_parameters is True
