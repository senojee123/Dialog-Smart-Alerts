"""The ``artifacts.json`` of a built basemap: what each file is, its checksum and the sources it was made
from. Written by the basemap build, read when the files are recorded with a release. Kept apart from
:mod:`app.pipeline.basemap` so that recording needs neither GDAL nor GeoPandas (the API image can do it).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.pipeline.errors import PipelineError
from app.services.reference_releases import ArtifactSourceSpec, ArtifactSpec


def write_artifacts(path: Path, artifacts: list[ArtifactSpec]) -> None:
    def encode(artifact: ArtifactSpec) -> dict[str, Any]:
        return {
            "kind": artifact.kind,
            "name": artifact.name,
            "uri": artifact.uri,
            "mediaType": artifact.media_type,
            "sha256": artifact.sha256,
            "sizeBytes": artifact.size_bytes,
            "crs": artifact.crs,
            "transformation": artifact.transformation,
            "minZoom": artifact.min_zoom,
            "maxZoom": artifact.max_zoom,
            "bounds": list(artifact.bounds) if artifact.bounds else None,
            "geometryTypes": list(artifact.geometry_types),
            "geometryAccuracyM": artifact.geometry_accuracy_m,
            "metadata": dict(artifact.metadata or {}),
            "toolVersions": dict(artifact.tool_versions or {}),
            "sources": [
                {
                    "source": item.source_code,
                    "role": item.role,
                    "reference": item.source_reference,
                    "version": item.source_version,
                    "sha256": item.source_checksum_sha256,
                    "retrievedAt": item.source_retrieved_at.isoformat() if item.source_retrieved_at else None,
                }
                for item in artifact.sources
            ],
        }

    document = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifacts": [encode(item) for item in artifacts],
    }
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def read_artifacts(directory: Path) -> list[ArtifactSpec]:
    """The artifacts a basemap build described, after checking the files still match their checksums."""
    path = directory / "artifacts.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PipelineError(f"cannot read {path}: {exc.strerror}") from exc
    artifacts = []
    for item in document["artifacts"]:
        local = directory / item["name"]
        if local.exists() and hashlib.sha256(local.read_bytes()).hexdigest() != item["sha256"]:
            raise PipelineError(f"{local} changed after the basemap was built; rebuild it")
        artifacts.append(
            ArtifactSpec(
                kind=item["kind"],
                name=item["name"],
                uri=item["uri"],
                media_type=item["mediaType"],
                sha256=item["sha256"],
                size_bytes=item["sizeBytes"],
                crs=item["crs"],
                transformation=item["transformation"],
                sources=[
                    ArtifactSourceSpec(
                        source["source"],
                        source["role"],
                        source["reference"],
                        source.get("version"),
                        source.get("sha256"),
                        datetime.fromisoformat(source["retrievedAt"]) if source.get("retrievedAt") else None,
                    )
                    for source in item["sources"]
                ],
                min_zoom=item.get("minZoom"),
                max_zoom=item.get("maxZoom"),
                bounds=tuple(item["bounds"]) if item.get("bounds") else None,
                geometry_types=item.get("geometryTypes", []),
                geometry_accuracy_m=item.get("geometryAccuracyM"),
                metadata=item.get("metadata") or {},
                tool_versions=item.get("toolVersions") or {},
            )
        )
    return artifacts
