"""Tenant identity (ADR-09).

Tenant isolation is enforced in PostgreSQL with row-level security. The tenant of the current
request is written to the transaction-local setting ``gis.tenant_id`` (see
``app.db.session.transaction``) and read by ``meta.current_tenant_id()`` inside RLS policies.

A request acts for one tenant: the one in its ``X-GIS-Tenant-Id`` header, else the platform's organisation
(``GIS_TENANT_ID``; see ``app.core.caller``). An event or query may name its tenant (``tenantId``), but the
API accepts only the tenant the request acts for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TENANT_SETTING = "gis.tenant_id"

# Lower-case slug or UUID: 2-63 characters, starting with a letter or digit.
TENANT_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,62}$"
_TENANT_PATTERN = re.compile(TENANT_ID_PATTERN)


@dataclass(frozen=True, slots=True)
class TenantId:
    value: str

    def __post_init__(self) -> None:
        if not _TENANT_PATTERN.fullmatch(self.value):
            raise ValueError("tenant id must be 2-63 lower-case letters, digits, '-' or '_'")

    def __str__(self) -> str:
        return self.value
