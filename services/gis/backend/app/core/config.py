"""Environment-based configuration.

All settings are read from environment variables prefixed with ``GIS_`` (see ``.env.example``
at the repository root). Secrets have no defaults and are held as ``SecretStr`` so they are never
logged or rendered by accident.
"""

from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

from app.core.tenancy import TENANT_ID_PATTERN

# backend/app/core/config.py -> repository root is three levels above the package directory.
# The container image keeps the same layout (/srv/backend/app, /srv/db).
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALEMBIC_CONFIG = REPOSITORY_ROOT / "db" / "alembic.ini"

# EPSG:5235 (SLD99 / Sri Lanka Grid 1999) area of use is "Sri Lanka - onshore":
# lon 79.64..81.95, lat 5.86..9.88 (EPSG registry). The default service area widens it by 0.2 degrees
# (about 22 km, the extent of the 12 nautical mile territorial sea) so nearshore positions are accepted.
DEFAULT_SERVICE_AREA_BBOX: tuple[float, float, float, float] = (79.44, 5.66, 82.15, 10.08)
# The database enforces the same envelope on every stored geometry (meta.is_within_sri_lanka, migration
# 20260915_0002). A deployment may narrow the service area, never widen it.
DATABASE_SERVICE_ENVELOPE: tuple[float, float, float, float] = DEFAULT_SERVICE_AREA_BBOX

_PG_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_VERSION = re.compile(r"^\d+\.\d+$")
_TENANT = re.compile(TENANT_ID_PATTERN)


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class DbSslMode(StrEnum):
    """Subset of libpq ``sslmode`` values understood by asyncpg."""

    DISABLE = "disable"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class DbRole(StrEnum):
    """Database login used for a connection.

    ``APP`` is the least-privilege runtime login. ``MIGRATOR`` owns the schemas and is used only by
    Alembic.
    """

    APP = "app"
    MIGRATOR = "migrator"


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        return [part.strip() for part in stripped.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GIS_", extra="ignore", frozen=True)

    # --- service ---------------------------------------------------------------------------------
    env: Environment = Environment.DEVELOPMENT
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: LogFormat = LogFormat.JSON
    api_root_path: str = ""
    docs_enabled: bool = True
    metrics_enabled: bool = True
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- database --------------------------------------------------------------------------------
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "gis"
    db_app_user: str = "gis_app"
    db_app_password: SecretStr | None = None
    db_migrator_user: str = "gis_migrator"
    db_migrator_password: SecretStr | None = None
    db_ssl_mode: DbSslMode = DbSslMode.DISABLE
    db_allow_insecure_transport: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0, le=100)
    db_pool_timeout_s: float = Field(default=10.0, gt=0)
    db_pool_recycle_s: int = Field(default=1800, ge=60)
    db_connect_timeout_s: float = Field(default=5.0, gt=0)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100)
    db_idle_in_transaction_timeout_ms: int = Field(default=30_000, ge=1_000)

    # --- spatial platform guarantees ------------------------------------------------------------
    postgis_min_version: str = "3.6"
    readiness_timeout_s: float = Field(default=3.0, gt=0, le=30)
    crs_consistency_tolerance_m: float = Field(default=0.1, gt=0)
    service_area_bbox: Annotated[tuple[float, float, float, float], NoDecode] = DEFAULT_SERVICE_AREA_BBOX

    # --- geo-context enrichment ------------------------------------------------------------------
    # Search radii are inclusive and in metres (EPSG:5235); a device limit of 0 turns the lookup off.
    enrichment_settlement_radius_m: float = Field(default=25_000.0, gt=0, le=100_000)
    enrichment_road_radius_m: float = Field(default=10_000.0, gt=0, le=100_000)
    enrichment_device_radius_m: float = Field(default=5_000.0, gt=0, le=100_000)
    enrichment_device_limit: int = Field(default=5, ge=0, le=50)
    max_request_body_bytes: int = Field(default=1_048_576, ge=1_024, le=16_777_216)

    # --- tenant --------------------------------------------------------------------------------------
    # The GIS runs as an instance of the main platform, which owns users and sign-in; the GIS checks no
    # credentials. A request acts for the tenant in its X-GIS-Tenant-Id header, else for this one. The
    # tenant must be registered (python -m app.tools.register_tenant, run by the migrate service).
    tenant_id: str = "dialog-smart-alerts"
    tenant_name: str = "Dialog Smart Alerts"

    # --- static files for the main platform --------------------------------------------------------
    # The platform image serves the built map application at /app and the basemaps at /basemap (with HTTP
    # range requests, which PMTiles needs), so the platform proxies one service. Empty: not served.
    web_dir: Path | None = None
    basemap_dir: Path | None = None

    # --- exports -------------------------------------------------------------------------------------
    # An export is one file; a request that would exceed this is refused rather than cut short.
    export_max_features: int = Field(default=10_000, ge=1, le=100_000)

    # --- migrations ------------------------------------------------------------------------------
    alembic_config_path: Path = DEFAULT_ALEMBIC_CONFIG

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("web_dir", "basemap_dir", mode="before")
    @classmethod
    def _blank_dir(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("tenant_id")
    @classmethod
    def _check_tenant(cls, value: str) -> str:
        if not _TENANT.fullmatch(value):
            raise ValueError("tenant_id must be 2-63 lower-case letters, digits, '-' or '_'")
        return value

    @field_validator("service_area_bbox", mode="before")
    @classmethod
    def _parse_bbox(cls, value: object) -> object:
        parsed = _split_csv(value)
        if isinstance(parsed, list):
            try:
                return tuple(float(part) for part in parsed)
            except ValueError as exc:
                raise ValueError(
                    "service_area_bbox must be four numbers: min_lon,min_lat,max_lon,max_lat"
                ) from exc
        return parsed

    @field_validator("service_area_bbox")
    @classmethod
    def _check_bbox(cls, value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        min_lon, min_lat, max_lon, max_lat = value
        if not (-180 <= min_lon < max_lon <= 180):
            raise ValueError("service_area_bbox longitudes must satisfy -180 <= min_lon < max_lon <= 180")
        if not (-90 <= min_lat < max_lat <= 90):
            raise ValueError("service_area_bbox latitudes must satisfy -90 <= min_lat < max_lat <= 90")
        env_min_lon, env_min_lat, env_max_lon, env_max_lat = DATABASE_SERVICE_ENVELOPE
        if min_lon < env_min_lon or min_lat < env_min_lat or max_lon > env_max_lon or max_lat > env_max_lat:
            raise ValueError(
                "service_area_bbox must lie within the envelope the database accepts "
                f"({','.join(str(v) for v in DATABASE_SERVICE_ENVELOPE)})"
            )
        return value

    @field_validator("db_app_user", "db_migrator_user", "db_name")
    @classmethod
    def _check_identifier(cls, value: str) -> str:
        if not _PG_IDENTIFIER.fullmatch(value):
            raise ValueError("must be a lower-case PostgreSQL identifier ([a-z_][a-z0-9_]{0,62})")
        return value

    @field_validator("postgis_min_version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        if not _VERSION.fullmatch(value):
            raise ValueError("postgis_min_version must look like MAJOR.MINOR, e.g. 3.6")
        return value

    @field_validator("api_root_path")
    @classmethod
    def _check_root_path(cls, value: str) -> str:
        if value and (not value.startswith("/") or value.endswith("/")):
            raise ValueError("api_root_path must start with '/' and must not end with '/'")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Self:
        if self.env is not Environment.PRODUCTION:
            return self
        if "*" in self.cors_allow_origins:
            raise ValueError("wildcard CORS origins are not allowed in production")
        if self.db_ssl_mode is DbSslMode.DISABLE and not self.db_allow_insecure_transport:
            raise ValueError(
                "production requires GIS_DB_SSL_MODE other than 'disable' "
                "(set GIS_DB_ALLOW_INSECURE_TRANSPORT=true only for a private, trusted network)"
            )
        if self.db_app_user == self.db_migrator_user:
            raise ValueError("the runtime login must differ from the migration login in production")
        return self

    @property
    def postgis_min_version_tuple(self) -> tuple[int, int]:
        major, minor = self.postgis_min_version.split(".")
        return int(major), int(minor)

    def database_url(self, role: DbRole = DbRole.APP) -> URL:
        """Build an asyncpg SQLAlchemy URL. Passwords are escaped by SQLAlchemy, never string-formatted."""
        if role is DbRole.APP:
            if self.db_app_password is None:
                raise ValueError("GIS_DB_APP_PASSWORD is required to run the API")
            user, password = self.db_app_user, self.db_app_password
        else:
            if self.db_migrator_password is None:
                raise ValueError("GIS_DB_MIGRATOR_PASSWORD is required to run database migrations")
            user, password = self.db_migrator_user, self.db_migrator_password
        return URL.create(
            drivername="postgresql+asyncpg",
            username=user,
            password=password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Tests call ``get_settings.cache_clear()`` after changing the environment."""
    return Settings()
