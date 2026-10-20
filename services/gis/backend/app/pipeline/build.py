"""Build a reference data release directory from a profile: acquire, stage, transform, check, write.

Output (``data/processed/<release>/``)::

    manifest.json            the release, its sources (licences as stated in the profile) and one entry per
                             file with full lineage and QA expectations - the loader's input
    <dataset>.geojson.gz     GIS-ready features (EPSG:4326), deterministic
    qa/<dataset>.qa.json     the file-level QA report of each dataset (stored with the load)
    build.json               profile, tool versions, every original file with its checksum and provenance
    SOURCES.md               attribution and licence obligations, for people

A dataset whose file QA fails is still written (so the report can be read) but the build fails and the
loader refuses the file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Final

import pyogrio
import pyproj

from app import __version__
from app.core.config import DEFAULT_SERVICE_AREA_BBOX
from app.pipeline import file_qa, gdal, writer
from app.pipeline.acquire import AcquiredSource, acquire
from app.pipeline.adapters import BuildContext, Note, adapter_for
from app.pipeline.errors import FileQaError, PipelineError
from app.pipeline.profile import Profile, check_licences, load_profile
from app.schemas.reference_data import FileSpec, Manifest, ReleaseSpec

logger = logging.getLogger(__name__)

STAGING_DIRECTORY: Final = ".staging"


@dataclass(slots=True)
class DatasetResult:
    name: str
    layer: str
    file: str
    sha256: str
    status: str
    counts: dict[str, int]


@dataclass(slots=True)
class BuildResult:
    release_code: str
    purpose: str
    directory: Path
    manifest: Path
    datasets: list[DatasetResult] = field(default_factory=list)
    sources: dict[str, AcquiredSource] = field(default_factory=dict)
    licence_notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "release": self.release_code,
            "purpose": self.purpose,
            "directory": str(self.directory),
            "datasets": [
                {"name": item.name, "layer": item.layer, "file": item.file, "qa": item.status, **item.counts}
                for item in self.datasets
            ],
            "licenceNotes": self.licence_notes,
        }


def tool_versions() -> dict[str, str]:
    versions = {
        "pipeline": f"gis-core-service {__version__}",
        "gdal": gdal.version_string(),
        "proj": str(pyproj.proj_version_str),
        "pyogrio_gdal": str(pyogrio.__gdal_version_string__),
        "python": platform.python_version(),
    }
    for package in ("geopandas", "shapely", "pyproj", "pyogrio", "pandas", "numpy"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:  # pragma: no cover - the pipeline extra installs them
            versions[package] = "not installed"
    return versions


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(
    profile_path: Path,
    *,
    raw_dir: Path,
    output_root: Path,
    release_code: str | None = None,
    only: set[str] | None = None,
    allow_download: bool = True,
    force: bool = False,
) -> BuildResult:
    profile = load_profile(profile_path)
    licence_notes = check_licences(profile)
    code = release_code or profile.profile.release_code()
    target = output_root / code
    if target.exists():
        if not force:
            raise PipelineError(
                f"{target} exists; use a new release code or --force to rebuild it",
                extensions={"directory": str(target)},
            )
        shutil.rmtree(target)
    (target / "qa").mkdir(parents=True)
    context = BuildContext(profile=profile, raw_dir=raw_dir, staging_dir=output_root / STAGING_DIRECTORY)
    context.staging_dir.mkdir(parents=True, exist_ok=True)
    versions = tool_versions()
    started = datetime.now(UTC)
    result = BuildResult(
        release_code=code,
        purpose=profile.profile.purpose,
        directory=target,
        manifest=target / "manifest.json",
        licence_notes=licence_notes,
    )
    datasets = [dataset for dataset in profile.datasets if only is None or dataset.name in only]
    unknown = sorted((only or set()) - {dataset.name for dataset in profile.datasets})
    if unknown:
        raise PipelineError(f"the profile has no dataset(s) {', '.join(unknown)}")
    files: list[FileSpec] = []
    failed: list[str] = []
    written: dict[str, dict[str, str]] = {}
    for dataset in datasets:
        source = profile.sources[dataset.source]
        if source.code not in result.sources:
            result.sources[source.code] = acquire(
                source, raw_dir, profile_dir=profile.directory, allow_download=allow_download
            )
        acquired = result.sources[source.code]
        logger.info("building dataset", extra={"dataset": dataset.name, "source": source.code})
        extracted = adapter_for(dataset.adapter)(context, dataset, source, acquired)
        # A feature selected by two datasets of one layer (a large tank in a national and a pilot dataset)
        # is written once: identifiers are unique per layer in a release.
        owners = written.setdefault(dataset.layer, {})
        repeated = extracted.frame["id"].isin(list(owners))
        for identifier in extracted.frame.loc[repeated, "id"]:
            extracted.notes.append(
                Note("transform.skipped", f"already in dataset {owners[identifier]}", str(identifier))
            )
        extracted.frame = extracted.frame[~repeated]
        expectations = profile.expectations(dataset)
        checked = file_qa.check(
            extracted, layer=dataset.layer, expectations=expectations, service_area=DEFAULT_SERVICE_AREA_BBOX
        )
        owners.update(dict.fromkeys(checked.frame["id"], dataset.name))
        file_name = f"{dataset.name}.geojson.gz"
        checksum = writer.write(target / file_name, writer.feature_collection(checked.frame))
        report = checked.report(file_name, checksum)
        report_name = f"qa/{dataset.name}.qa.json"
        (target / report_name).write_text(
            report.model_dump_json(by_alias=True, indent=1) + "\n", encoding="utf-8"
        )
        if checked.status == "failed":
            failed.append(dataset.name)
        result.datasets.append(
            DatasetResult(dataset.name, dataset.layer, file_name, checksum, checked.status, checked.counts)
        )
        files.append(
            FileSpec(
                path=file_name,
                layer=dataset.layer,
                source=source.code,
                source_reference=acquired.reference,
                source_version=acquired.version,
                source_retrieved_at=acquired.retrieved_at,
                original_file=acquired.path.name,
                original_checksum_sha256=acquired.sha256,
                source_crs=extracted.source_crs,
                coordinate_operation=None
                if extracted.operation.is_identity
                else extracted.operation.lineage(),
                transformation=extracted.transformation,
                geometry_source=dataset.geometry_source or source.geometry_source,
                geometry_accuracy_m=dataset.accuracy_m,
                parent_by=dataset.parent_by,
                admin_area_by=dataset.admin_area_by,
                qa=expectations,
                qa_report=report_name,
                tool_versions=versions,
            )
        )
    used_sources = {spec.source for spec in files}
    if profile.basemap is not None:
        # Registered with the release so that the basemap's artifacts can name them.
        used_sources |= {profile.basemap.osm_source, profile.basemap.land_source}
        if profile.basemap.glyphs_source is not None:
            used_sources.add(profile.basemap.glyphs_source)
    used = sorted(used_sources)
    manifest = Manifest(
        release=ReleaseSpec(
            code=code, purpose=profile.profile.purpose, description=profile.profile.description
        ),
        sources=[profile.sources[source].spec() for source in used],
        files=files,
    )
    result.manifest.write_text(
        manifest.model_dump_json(by_alias=True, exclude_none=True, exclude_defaults=False, indent=1) + "\n",
        encoding="utf-8",
    )
    _write_build_record(result, profile, profile_path, versions, started)
    _write_sources(result, profile)
    if failed:
        raise FileQaError(
            f"file QA failed for {', '.join(failed)}; see {target / 'qa'}",
            extensions={"datasets": failed, "directory": str(target)},
        )
    return result


def _write_build_record(
    result: BuildResult, profile: Profile, profile_path: Path, versions: dict[str, str], started: datetime
) -> None:
    record = {
        "release": result.release_code,
        "purpose": result.purpose,
        "profile": {"name": profile.profile.name, "file": profile_path.name, "sha256": _sha256(profile_path)},
        "startedAt": started.isoformat(),
        "finishedAt": datetime.now(UTC).isoformat(),
        "toolVersions": versions,
        "areas": {name: list(box) for name, box in profile.areas.items()},
        "sources": {
            code: {
                "file": item.path.name,
                "sha256": item.sha256,
                "sizeBytes": item.size_bytes,
                "reference": item.reference,
                "version": item.version,
                "retrievedAt": item.retrieved_at.isoformat() if item.retrieved_at else None,
                "retrievedBasis": item.retrieved_basis,
            }
            for code, item in sorted(result.sources.items())
        },
        "datasets": result.summary()["datasets"],
        "licenceNotes": result.licence_notes,
    }
    (result.directory / "build.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _write_sources(result: BuildResult, profile: Profile) -> None:
    by_source: dict[str, list[DatasetResult]] = {}
    for dataset in result.datasets:
        source = next(item.source for item in profile.datasets if item.name == dataset.name)
        by_source.setdefault(source, []).append(dataset)
    lines = [
        f"# Reference data release `{result.release_code}` ({result.purpose})",
        "",
        profile.profile.description,
        "",
        "Built by the reference data pipeline (`python -m app.pipeline build`). The lineage of every file "
        "is in",
        "`manifest.json` and `build.json`; the QA report of every dataset is in `qa/`.",
        "",
        "## Sources, licences and attribution",
        "",
        "| Source | Licence | Commercial use | Redistribution | Review | Attribution | Version | Datasets |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for code, datasets in sorted(by_source.items()):
        described = profile.sources[code]
        acquired = result.sources[code]
        licence = (
            f"[{described.licence}]({described.licence_url})" if described.licence_url else described.licence
        )
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    f"{described.name} ({described.publisher})",
                    licence + (" (share-alike)" if described.share_alike else ""),
                    "yes"
                    if described.commercial_use_allowed
                    else f"by permission: {described.permission_reference}",
                    "yes" if described.redistribution_allowed else "no",
                    described.review.status,
                    described.attribution,
                    acquired.version,
                    ", ".join(f"`{item.file}`" for item in datasets),
                )
            )
            + " |"
        )
    lines += [
        "",
        "## Original files",
        "",
        "| Source | File | SHA-256 | Retrieved | From |",
        "|---|---|---|---|---|",
    ]
    for code, acquired in sorted(result.sources.items()):
        retrieved = acquired.retrieved_at.isoformat() if acquired.retrieved_at else "unknown"
        lines.append(
            f"| {code} | `{acquired.path.name}` | `{acquired.sha256}` | {retrieved} "
            f"({_cell(acquired.retrieved_basis)}) "
            f"| {_cell(acquired.reference)} |"
        )
    lines += [
        "",
        "## Datasets",
        "",
        "| File | Layer | Features | Left out | File QA |",
        "|---|---|---|---|---|",
    ]
    for dataset in result.datasets:
        lines.append(
            f"| `{dataset.file}` | {dataset.layer} | {dataset.counts.get('written', 0)} | "
            f"{dataset.counts.get('leftOut', 0)} | {dataset.status} |"
        )
    notes = [f"* {note}" for note in result.licence_notes]
    if result.purpose != "production":
        notes.append(
            f"* This is a **{result.purpose}** release: licences are not reviewed for production use and "
            "it may "
            "contain labelled placeholders. It cannot be made current in a production environment."
        )
    if notes:
        lines += ["", "## Obligations and notes", "", *notes]
    (result.directory / "SOURCES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
