"""Reference data pipeline command line: ``python -m app.pipeline <command>`` (from ``backend/``).

Building (needs GDAL and the ``pipeline`` extra; no database)::

    sources  --profile P                 the sources of a profile, their licences and reviews
    fetch    --profile P                 download or locate the original files, verify checksums
    build    --profile P [--release C]   build data/processed/<release>/ (GeoJSON, manifest, QA reports)
    basemap  --profile P --release C     build the PMTiles basemap, style and glyphs for a release

Releasing (the migration login's ``GIS_DB_*`` settings; each step is its own transaction)::

    load     DIR [--basemap B] [--publish] [--current]
                                         load a built release directory into a draft release (with the
                                         basemap directory B as its artifacts), run QA, publish
    qa       RELEASE                     run the database QA checks on a draft release
    waive    RELEASE FINDING --reason T  accept one QA error, with a reason (recorded and audited)
    publish  RELEASE [--current]         publish a draft that passed QA (and make it current)
    current  RELEASE                     make a published release the current one
    retire   RELEASE                     retire a published release that is not current
    status   [RELEASE]                   list releases, or report one: datasets, lineage, licences, QA
    diff     RELEASE [--against R]       feature counts and ids added/removed against another release
    artifacts RELEASE DIR                record a built basemap as artifacts of a draft release

    run      --profile P [--publish] [--current] [--basemap]   build, load, check (and publish)

Every command prints JSON. Changes are recorded in the audit log with ``--actor`` (default: the
operating-system login) and channel ``loader``. In a production environment (``GIS_ENV=production``)
only a production release can be made current.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import Access
from app.core.config import REPOSITORY_ROOT, DbRole, get_settings
from app.core.errors import GisError
from app.core.logging import configure_logging
from app.db.engine import create_engine, create_session_factory
from app.db.session import access_transaction
from app.spatial.service_area import ServiceArea

logger = logging.getLogger("app.pipeline")

DEFAULT_RAW_DIR = REPOSITORY_ROOT / "data" / "raw"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "data" / "processed"
DEFAULT_BASEMAP_DIR = REPOSITORY_ROOT / "data" / "basemap"


def _actor(value: str | None) -> str:
    if value is not None and value.strip():
        return value.strip()
    try:
        return getpass.getuser()
    except (KeyError, OSError):  # no login name for this uid (some containers)
        return "unknown-operator"


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


async def _in_transaction[T](actor: str, work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    settings = get_settings()
    engine = create_engine(settings, DbRole.MIGRATOR)
    try:
        access = Access.system(actor, channel="loader")
        async with access_transaction(create_session_factory(engine), access) as session:
            return await work(session)
    finally:
        await engine.dispose()


# --- building ---------------------------------------------------------------------------------------------


def cmd_sources(args: argparse.Namespace) -> Any:
    from app.pipeline.profile import check_licences, load_profile

    profile = load_profile(args.profile)
    notes = check_licences(profile)
    return {
        "profile": profile.profile.name,
        "purpose": profile.profile.purpose,
        "sources": [
            {
                "code": source.code,
                "name": source.name,
                "licence": source.licence,
                "commercialUseAllowed": source.commercial_use_allowed,
                "redistributionAllowed": source.redistribution_allowed,
                "shareAlike": source.share_alike,
                "permissionReference": source.permission_reference,
                "review": source.review.model_dump(mode="json", by_alias=True, exclude_none=True),
                "file": source.file,
                "download": source.download or (f"${source.download_env}" if source.download_env else None),
            }
            for source in profile.sources.values()
        ],
        "notes": notes,
    }


def cmd_fetch(args: argparse.Namespace) -> Any:
    from app.pipeline.acquire import acquire
    from app.pipeline.profile import check_licences, load_profile

    profile = load_profile(args.profile)
    check_licences(profile)
    used = {dataset.source for dataset in profile.datasets}
    if profile.basemap is not None:
        used |= {profile.basemap.osm_source, profile.basemap.land_source}
    fetched = []
    for code in sorted(used):
        item = acquire(
            profile.sources[code], args.raw_dir, profile_dir=profile.directory, allow_download=True
        )
        fetched.append(
            {
                "source": code,
                "file": str(item.path),
                "sha256": item.sha256,
                "version": item.version,
                "retrievedAt": item.retrieved_at,
                "retrievedBasis": item.retrieved_basis,
            }
        )
    return {"sources": fetched}


def cmd_build(args: argparse.Namespace) -> Any:
    from app.pipeline.build import build

    result = build(
        args.profile,
        raw_dir=args.raw_dir,
        output_root=args.output_dir,
        release_code=args.release,
        only=set(args.only.split(",")) if args.only else None,
        allow_download=not args.no_download,
        force=args.force,
    )
    return result.summary()


def cmd_basemap(args: argparse.Namespace) -> Any:
    from app.pipeline.basemap import build_basemap

    result = build_basemap(
        args.profile,
        release_code=args.release,
        raw_dir=args.raw_dir,
        output_root=args.basemap_dir,
        staging_dir=args.output_dir / ".staging",
        allow_download=not args.no_download,
    )
    return result.summary()


# --- releasing --------------------------------------------------------------------------------------------


async def cmd_load(args: argparse.Namespace) -> Any:
    from app.services.reference_loader import ReferenceDataLoader
    from app.services.reference_releases import ReleaseManager

    settings = get_settings()
    actor = _actor(args.actor)
    manifest = args.directory / "manifest.json" if args.directory.is_dir() else args.directory

    async def load(session: AsyncSession) -> Any:
        loader = ReferenceDataLoader(session, ServiceArea.from_bbox(settings.service_area_bbox))
        return await loader.load(manifest, release_code=args.release)

    loaded = await _in_transaction(actor, load)
    basemap = getattr(args, "basemap_directory", None)
    artifacts = None
    if basemap is not None:
        # Recorded while the release is a draft: a published release does not change.
        artifacts = await _register_artifacts(actor, loaded.release_code, basemap)
    output: dict[str, Any] = {
        "release": loaded.release_code,
        "purpose": loaded.purpose,
        "files": [
            {
                "path": item.path,
                "layer": item.layer,
                "sourceFeatures": item.source_features,
                "loaded": item.loaded,
                "repaired": item.repaired,
                "rejected": item.rejected,
                "fileQa": item.file_qa,
            }
            for item in loaded.files
        ],
    }
    if artifacts is not None:
        output["artifacts"] = artifacts
    qa = await _in_transaction(actor, lambda session: ReleaseManager(session).run_qa(loaded.release_code))
    output["qa"] = qa.as_dict()
    if (args.publish or args.current) and qa.status != "failed":
        record = await _in_transaction(
            actor,
            lambda session: ReleaseManager(session).publish(
                loaded.release_code, make_current=args.current, environment=settings.env
            ),
        )
        output.update(published=record.status == "published", current=record.is_current)
    return output


async def cmd_qa(args: argparse.Namespace) -> Any:
    from app.services.reference_releases import ReleaseManager

    summary = await _in_transaction(
        _actor(args.actor), lambda session: ReleaseManager(session).run_qa(args.release)
    )
    return summary.as_dict(limit=args.limit)


async def cmd_waive(args: argparse.Namespace) -> Any:
    from app.services.reference_releases import ReleaseManager

    await _in_transaction(
        _actor(args.actor),
        lambda session: ReleaseManager(session).waive(args.release, args.finding, args.reason),
    )
    return {"release": args.release, "finding": args.finding, "waived": True}


async def cmd_publish(args: argparse.Namespace) -> Any:
    from app.services.reference_releases import ReleaseManager

    environment = get_settings().env
    record = await _in_transaction(
        _actor(args.actor),
        lambda session: ReleaseManager(session).publish(
            args.release, make_current=args.current, environment=environment
        ),
    )
    return {"release": record.code, "status": record.status, "current": record.is_current}


async def cmd_current(args: argparse.Namespace) -> Any:
    from app.services.reference_releases import ReleaseManager

    environment = get_settings().env
    record = await _in_transaction(
        _actor(args.actor),
        lambda session: ReleaseManager(session).make_current(args.release, environment=environment),
    )
    return {"release": record.code, "status": record.status, "current": record.is_current}


async def cmd_retire(args: argparse.Namespace) -> Any:
    from app.services.reference_releases import ReleaseManager

    record = await _in_transaction(
        _actor(args.actor), lambda session: ReleaseManager(session).retire(args.release)
    )
    return {"release": record.code, "status": record.status}


async def cmd_status(args: argparse.Namespace) -> Any:
    from app.services.reference_releases import ReleaseManager

    async def status(session: AsyncSession) -> Any:
        manager = ReleaseManager(session)
        if args.release is None:
            return [
                {
                    "release": item.code,
                    "status": item.status,
                    "purpose": item.purpose,
                    "current": item.is_current,
                    "publishedAt": item.published_at,
                }
                for item in await manager.releases()
            ]
        return await manager.report(args.release, findings_limit=args.limit)

    return await _in_transaction(_actor(args.actor), status)


async def cmd_diff(args: argparse.Namespace) -> Any:
    from app.services.reference_releases import ReleaseManager

    return await _in_transaction(
        _actor(args.actor), lambda session: ReleaseManager(session).diff(args.release, args.against)
    )


async def _register_artifacts(actor: str, release: str, directory: Path) -> dict[str, Any]:
    from app.pipeline.artifacts import read_artifacts
    from app.services.reference_releases import ReleaseManager

    artifacts = read_artifacts(directory)

    async def register(session: AsyncSession) -> Any:
        manager = ReleaseManager(session)
        return [str(await manager.register_artifact(release, artifact)) for artifact in artifacts]

    ids = await _in_transaction(actor, register)
    return {"release": release, "artifacts": [item.name for item in artifacts], "ids": ids}


async def cmd_artifacts(args: argparse.Namespace) -> Any:
    return await _register_artifacts(_actor(args.actor), args.release, args.directory)


async def cmd_run(args: argparse.Namespace) -> Any:
    built = cmd_build(args)
    output: dict[str, Any] = {"build": built}
    if args.basemap:
        args.release = built["release"]
        output["basemap"] = cmd_basemap(args)
    args.directory = Path(built["directory"])
    args.basemap_directory = args.basemap_dir / built["release"] if args.basemap else None
    args.release = None
    # Loads, records the basemap, checks and (when asked and QA allows it) publishes.
    output["load"] = await cmd_load(args)
    return output


# --- parser -----------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.pipeline", description=__doc__.split("\n\n")[0])
    parser.add_argument("--actor", help="who runs the command, for the audit log (default: the OS login)")
    commands = parser.add_subparsers(dest="command", required=True)

    def profile_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--profile", type=Path, required=True, help="pipeline profile (TOML)")
        command.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="original source files")
        command.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="built releases")
        command.add_argument("--basemap-dir", type=Path, default=DEFAULT_BASEMAP_DIR, help="built basemaps")
        command.add_argument("--no-download", action="store_true", help="fail instead of downloading")

    def build_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--release", help="release code (default: the profile's template)")
        command.add_argument("--only", help="comma-separated dataset names to build")
        command.add_argument("--force", action="store_true", help="rebuild an existing release directory")

    sources = commands.add_parser("sources", help="list a profile's sources and licences")
    profile_options(sources)
    fetch = commands.add_parser("fetch", help="download or locate the original files")
    profile_options(fetch)
    build = commands.add_parser("build", help="build a release directory")
    profile_options(build)
    build_options(build)
    basemap = commands.add_parser("basemap", help="build the basemap of a release")
    profile_options(basemap)
    basemap.add_argument("--release", required=True)

    load = commands.add_parser("load", help="load a built release directory and run QA")
    load.add_argument("directory", type=Path, help="release directory (or its manifest.json)")
    load.add_argument("--release", help="load under another release code")
    load.add_argument("--publish", action="store_true")
    load.add_argument("--current", action="store_true")
    load.add_argument(
        "--basemap",
        dest="basemap_directory",
        type=Path,
        help="built basemap directory of this release, recorded as its artifacts before QA",
    )
    for name, text in (
        ("qa", "run the database QA checks"),
        ("current", "make a release current"),
        ("retire", "retire a release"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("release")
        if name == "qa":
            command.add_argument("--limit", type=int, default=25, help="findings to print")
    waive = commands.add_parser("waive", help="accept a QA error with a reason")
    waive.add_argument("release")
    waive.add_argument("finding", type=int)
    waive.add_argument("--reason", required=True)
    publish = commands.add_parser("publish", help="publish a draft release")
    publish.add_argument("release")
    publish.add_argument("--current", action="store_true")
    status = commands.add_parser("status", help="list releases or report one")
    status.add_argument("release", nargs="?")
    status.add_argument("--limit", type=int, default=200, help="QA findings to include")
    diff = commands.add_parser("diff", help="compare a release with another")
    diff.add_argument("release")
    diff.add_argument("--against")
    artifacts = commands.add_parser("artifacts", help="record a built basemap as release artifacts")
    artifacts.add_argument("release")
    artifacts.add_argument("directory", type=Path)
    run = commands.add_parser("run", help="build, load, check and optionally publish")
    profile_options(run)
    build_options(run)
    run.add_argument("--publish", action="store_true")
    run.add_argument("--current", action="store_true")
    run.add_argument("--basemap", action="store_true", help="also build and record the basemap")
    return parser


SYNC = {"sources": cmd_sources, "fetch": cmd_fetch, "build": cmd_build, "basemap": cmd_basemap}
ASYNC = {
    "load": cmd_load,
    "qa": cmd_qa,
    "waive": cmd_waive,
    "publish": cmd_publish,
    "current": cmd_current,
    "retire": cmd_retire,
    "status": cmd_status,
    "diff": cmd_diff,
    "artifacts": cmd_artifacts,
    "run": cmd_run,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        command = args.command
        result = SYNC[command](args) if command in SYNC else asyncio.run(ASYNC[command](args))
    except GisError as exc:
        print(_json({"error": exc.code, "detail": exc.detail, **exc.extensions}), file=sys.stderr)
        return 1
    print(_json(result))
    if isinstance(result, dict):
        qa = result.get("qa") if "qa" in result else result.get("load", {}).get("qa")
        if isinstance(qa, dict) and qa.get("status") == "failed":
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
