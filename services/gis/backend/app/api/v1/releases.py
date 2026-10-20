"""``/geo/v1/releases``: the published reference data releases and the lineage of every dataset in them.

Answers "where does this come from?" for any reference feature: each release lists its datasets with the
source, licence and attribution as they were when the data was imported, the source's URL or reference
and version, when it was retrieved, the source CRS and the coordinate operation applied, the geometry
types, the nominal accuracy and the counts; the files built for it (basemap); and the QA run it was
published after. Events keep the code of the release their geo-context was computed with
(``refDataRelease``), so this is also how an old answer is traced.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.api.deps import PrincipalDep, ReleaseCatalogueDep
from app.api.v1.problems import problem, requires
from app.core.access import Permission
from app.schemas.reference_data import RELEASE_CODE_PATTERN
from app.schemas.releases import ReleaseDetail, ReleaseList

router = APIRouter(tags=["reference-data"])


@router.get(
    "/releases",
    operation_id="listReleases",
    response_model=ReleaseList,
    summary="Published reference data releases",
    description="Published and retired reference data releases, the current one first, with their purpose "
    "(production, development, test), dataset and feature counts. Drafts are not listed.",
    responses={},
    openapi_extra=requires(Permission.MAP_READ),
)
async def list_releases(
    principal: PrincipalDep, catalogue: ReleaseCatalogueDep, response: Response
) -> ReleaseList:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "private, max-age=60"
    return await catalogue.releases()


@router.get(
    "/releases/{code}",
    operation_id="getRelease",
    response_model=ReleaseDetail,
    summary="A reference data release and its lineage",
    description="One published or retired release: every dataset with its source, licence and attribution "
    "(as imported), source reference and version, retrieval and import times, CRS and coordinate operation, "
    "geometry types, accuracy and counts; the basemap files built for it; and its QA result.",
    responses={
        status.HTTP_404_NOT_FOUND: problem(
            404,
            "release_not_found",
            "Reference data release not found",
            "No published or retired release has this code.",
            "/geo/v1/releases/ref-2001.01",
        ),
    },
    openapi_extra=requires(Permission.MAP_READ),
)
async def get_release(
    code: Annotated[str, Path(pattern=RELEASE_CODE_PATTERN, examples=["ref-2026.09-dev"])],
    principal: PrincipalDep,
    catalogue: ReleaseCatalogueDep,
    response: Response,
) -> ReleaseDetail:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "private, max-age=60"
    return await catalogue.release(code)
