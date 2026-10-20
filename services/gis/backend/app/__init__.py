"""GIS Core Service.

Authoritative PostGIS spatial storage, geo-context enrichment and spatial query APIs for the
geo-aware event intelligence platform. See ARCHITECTURE.md at the repository root for the
service boundary (GIS only: no alerting or notification responsibilities).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gis-core-service")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0+unknown"

SERVICE_NAME = "gis-core-service"
