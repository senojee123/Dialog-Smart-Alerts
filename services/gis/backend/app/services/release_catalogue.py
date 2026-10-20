"""Read-only view of the published reference data releases, for the API (``/geo/v1/releases``).

Everything comes from the lineage recorded at load time (``meta.dataset_lineage``), the release artifacts
and the QA run the release was published after. Drafts are not shown. Nothing here is tenant data.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFoundError
from app.db.session import transaction
from app.schemas.reference_data import merge_attribution
from app.schemas.releases import (
    ArtifactSource,
    DatasetLineage,
    ReleaseArtifactOut,
    ReleaseDetail,
    ReleaseList,
    ReleaseQa,
    ReleaseSummary,
)


class PublishedReleaseNotFoundError(NotFoundError):
    code = "release_not_found"
    title = "Reference data release not found"


_SUMMARIES = """
    SELECT r.id, r.code, r.status, r.purpose, r.is_current, r.description, r.published_at, r.retired_at,
           count(l.id) FILTER (WHERE l.status = 'completed') AS datasets,
           coalesce(sum(l.loaded_count) FILTER (WHERE l.status = 'completed'), 0) AS features
    FROM meta.ref_data_release AS r
    LEFT JOIN meta.dataset_load AS l ON l.release_id = r.id
    WHERE r.status IN ('published', 'retired') {where}
    GROUP BY r.id
    ORDER BY r.is_current DESC, r.published_at DESC NULLS LAST, r.code
"""
_LIST = text(_SUMMARIES.format(where=""))
_ONE = text(_SUMMARIES.format(where="AND r.code = :code"))
_LINEAGE = text(
    """
    SELECT layer_code, source_code, source_name, publisher, licence, licence_url, attribution,
           commercial_use_allowed, redistribution_allowed, share_alike, licence_review_status,
           source_reference,
           source_version, source_retrieved_at, source_file, source_checksum_sha256, original_file,
           original_checksum_sha256, source_crs, storage_crs, coordinate_operation, transformation,
           geometry_types, geometry_accuracy_m, source_feature_count, loaded_count, repaired_count,
           rejected_count, imported_at, finished_at
    FROM meta.dataset_lineage
    WHERE release_id = :release_id AND load_status = 'completed'
    ORDER BY layer_code COLLATE "C", imported_at, source_file COLLATE "C"
    """
).bindparams(bindparam("release_id", type_=UUID))
_ARTIFACTS = text(
    """
    SELECT a.kind, a.name, a.uri, a.media_type, a.sha256, a.size_bytes, a.crs, a.min_zoom, a.max_zoom,
           coalesce((SELECT jsonb_agg(jsonb_build_object(
                        'source', s.code, 'role', x.role, 'licence', x.licence, 'attribution', x.attribution,
                        'version', x.source_version, 'reference', x.source_reference) ORDER BY s.code)
                     FROM meta.release_artifact_source AS x JOIN meta.data_source AS s ON s.id = x.source_id
                     WHERE x.artifact_id = a.id), '[]'::jsonb) AS sources
    FROM meta.release_artifact AS a
    WHERE a.release_id = :release_id
    ORDER BY a.kind, a.name
    """
).bindparams(bindparam("release_id", type_=UUID))
_QA = text(
    """
    SELECT q.status, q.finished_at, q.check_count, q.error_count, q.warning_count, q.info_count,
           (SELECT count(*) FROM meta.qa_finding AS f
            WHERE f.run_id = q.id AND f.severity = 'error' AND f.waived_at IS NOT NULL) AS waived
    FROM meta.qa_run AS q
    WHERE q.release_id = :release_id AND q.stage = 'database' AND q.status <> 'running'
    ORDER BY q.started_at DESC, q.id DESC
    LIMIT 1
    """
).bindparams(bindparam("release_id", type_=UUID))


def _summary(row: Any) -> ReleaseSummary:
    return ReleaseSummary(
        code=row.code,
        status=row.status,
        purpose=row.purpose,
        is_current=row.is_current,
        description=row.description,
        published_at=row.published_at,
        retired_at=row.retired_at,
        datasets=int(row.datasets),
        features=int(row.features),
    )


class ReleaseCatalogue:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def releases(self) -> ReleaseList:
        async with transaction(self._session_factory) as session:
            rows = (await session.execute(_LIST)).all()
        return ReleaseList(releases=[_summary(row) for row in rows])

    async def release(self, code: str) -> ReleaseDetail:
        async with transaction(self._session_factory) as session:
            row = (await session.execute(_ONE, {"code": code})).one_or_none()
            if row is None:
                raise PublishedReleaseNotFoundError(
                    f"no published reference data release {code}", extensions={"refDataRelease": code}
                )
            lineage = (await session.execute(_LINEAGE, {"release_id": row.id})).mappings().all()
            artifacts = (await session.execute(_ARTIFACTS, {"release_id": row.id})).mappings().all()
            qa = (await session.execute(_QA, {"release_id": row.id})).one_or_none()
        summary = _summary(row)
        datasets = [
            DatasetLineage(
                layer=item["layer_code"],
                source=item["source_code"],
                source_name=item["source_name"],
                publisher=item["publisher"],
                licence=item["licence"],
                licence_url=item["licence_url"],
                attribution=item["attribution"],
                commercial_use_allowed=item["commercial_use_allowed"],
                redistribution_allowed=item["redistribution_allowed"],
                share_alike=item["share_alike"],
                licence_review=item["licence_review_status"],
                source_reference=item["source_reference"],
                source_version=item["source_version"],
                source_retrieved_at=item["source_retrieved_at"],
                source_file=item["source_file"],
                source_checksum_sha256=item["source_checksum_sha256"],
                original_file=item["original_file"],
                original_checksum_sha256=item["original_checksum_sha256"],
                source_crs=item["source_crs"],
                storage_crs=item["storage_crs"],
                coordinate_operation=item["coordinate_operation"],
                transformation=item["transformation"],
                geometry_types=list(item["geometry_types"] or []),
                geometry_accuracy_m=None
                if item["geometry_accuracy_m"] is None
                else float(item["geometry_accuracy_m"]),
                source_features=item["source_feature_count"],
                loaded=item["loaded_count"],
                repaired=item["repaired_count"],
                rejected=item["rejected_count"],
                imported_at=item["imported_at"],
                finished_at=item["finished_at"],
            )
            for item in lineage
        ]
        artifact_list = [
            ReleaseArtifactOut(
                kind=item["kind"],
                name=item["name"],
                uri=item["uri"],
                media_type=item["media_type"],
                sha256=item["sha256"],
                size_bytes=item["size_bytes"],
                crs=item["crs"],
                min_zoom=item["min_zoom"],
                max_zoom=item["max_zoom"],
                sources=[ArtifactSource.model_validate(source) for source in item["sources"]],
            )
            for item in artifacts
        ]
        attribution = merge_attribution(
            [item.attribution for item in datasets]
            + [source.attribution for artifact in artifact_list for source in artifact.sources]
        )
        return ReleaseDetail(
            **summary.model_dump(),
            attribution=attribution,
            dataset_lineage=datasets,
            artifacts=artifact_list,
            qa=None
            if qa is None
            else ReleaseQa(
                status=qa.status,
                finished_at=qa.finished_at,
                checks=qa.check_count,
                errors=qa.error_count,
                warnings=qa.warning_count,
                infos=qa.info_count,
                waived_errors=int(qa.waived),
            ),
        )
