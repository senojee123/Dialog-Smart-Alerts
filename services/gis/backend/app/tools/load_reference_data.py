"""Load a reference data manifest into a release.

Usage (from ``backend/``, with the ``GIS_DB_*`` variables of the migration login set)::

    python -m app.tools.load_reference_data ../data/fixtures/lka_open/manifest.json --publish --current

The whole load runs in one transaction: on any error nothing is written. Creating, publishing and making
a release current is recorded in the audit log with ``--actor`` (default: the operating-system login) as
the actor and ``loader`` as the channel.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

from app.core.access import Access
from app.core.config import DbRole, get_settings
from app.core.errors import GisError
from app.core.logging import configure_logging
from app.db.engine import create_engine, create_session_factory
from app.db.session import access_transaction
from app.services.reference_loader import LoadResult, ReferenceDataLoader
from app.spatial.service_area import ServiceArea


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("manifest", type=Path, help="manifest.json describing sources and files")
    parser.add_argument("--release", help="release code (default: the code in the manifest)")
    parser.add_argument("--publish", action="store_true", help="publish the release after loading")
    parser.add_argument("--current", action="store_true", help="publish and make it the current release")
    parser.add_argument(
        "--actor",
        default=None,
        help="who runs the load, as recorded in the audit log (default: the operating-system login)",
    )
    return parser


def _actor(value: str | None) -> str:
    if value is not None and value.strip():
        return value.strip()
    try:
        return getpass.getuser()
    except (KeyError, OSError):  # no login name for this uid (some containers)
        return "unknown-operator"


def summary(result: LoadResult) -> dict[str, object]:
    return {
        "release": result.release_code,
        "published": result.published,
        "current": result.current,
        "files": [
            {
                "path": item.path,
                "layer": item.layer,
                "sourceFeatures": item.source_features,
                "loaded": item.loaded,
                "repaired": item.repaired,
                "rejected": item.rejected,
            }
            for item in result.files
        ],
    }


async def run(args: argparse.Namespace) -> LoadResult:
    settings = get_settings()
    engine = create_engine(settings, DbRole.MIGRATOR)
    try:
        access = Access.system(_actor(args.actor), channel="loader")
        async with access_transaction(create_session_factory(engine), access) as session:
            loader = ReferenceDataLoader(session, ServiceArea.from_bbox(settings.service_area_bbox))
            return await loader.load(
                args.manifest, release_code=args.release, publish=args.publish, make_current=args.current
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        result = asyncio.run(run(args))
    except GisError as exc:
        print(
            json.dumps({"error": exc.code, "detail": exc.detail, **exc.extensions}, indent=2), file=sys.stderr
        )
        return 1
    print(json.dumps(summary(result), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
