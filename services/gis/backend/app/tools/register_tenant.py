"""Register the platform's organisation as a GIS tenant.

Usage (from ``backend/``, with the ``GIS_DB_*`` variables of the migration login set)::

    python -m app.tools.register_tenant            # GIS_TENANT_ID / GIS_TENANT_NAME
    python -m app.tools.register_tenant --tenant other-org --name "Other organisation"

Requests act for ``GIS_TENANT_ID`` unless they name another tenant (``X-GIS-Tenant-Id``), and the GIS
answers ``403 tenant_not_registered`` for a tenant it does not know. Registering is idempotent: an existing
tenant is left as it is. The ``migrate`` service runs this after the migrations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from sqlalchemy import text

from app.core.config import DbRole, Settings, get_settings
from app.core.logging import configure_logging
from app.core.tenancy import TenantId
from app.db.engine import create_engine, create_session_factory
from app.db.session import transaction


async def register(settings: Settings, tenant: TenantId, name: str) -> bool:
    """Register ``tenant``; True when it was created, False when it already existed."""
    engine = create_engine(settings, DbRole.MIGRATOR)
    try:
        async with transaction(create_session_factory(engine)) as session:
            created = await session.execute(
                text(
                    "INSERT INTO meta.tenant (tenant_id, name) VALUES (:tenant_id, :name) "
                    "ON CONFLICT (tenant_id) DO NOTHING RETURNING tenant_id"
                ),
                {"tenant_id": tenant.value, "name": name},
            )
            return created.scalar_one_or_none() is not None
    finally:
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tenant", help="tenant id (default: GIS_TENANT_ID)")
    parser.add_argument("--name", help="display name (default: GIS_TENANT_NAME)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        tenant = TenantId(args.tenant or settings.tenant_id)
    except ValueError as exc:
        print(json.dumps({"error": "invalid_tenant", "detail": str(exc)}), file=sys.stderr)
        return 1
    created = asyncio.run(register(settings, tenant, args.name or settings.tenant_name))
    print(json.dumps({"tenantId": tenant.value, "created": created}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
