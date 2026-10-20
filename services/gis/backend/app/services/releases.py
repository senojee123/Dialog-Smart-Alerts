"""Reference data releases: which one a request reads, and whether it may be used.

Every answer about reference data names the release it came from, and only a *published* release (or one
retired after having been published) may be read: a draft is still being loaded, so its features and
counts are not final. Enrichment and the query API resolve releases the same way, so the same event and
the same query see the same data.
"""

from __future__ import annotations

from typing import Final

from app.core.errors import GisValidationError, NotFoundError, ServiceUnavailableError
from app.repositories.spatial_lookup import ReleaseRow

USABLE_RELEASE_STATUSES: Final = frozenset({"published", "retired"})


class ReferenceDataUnavailableError(ServiceUnavailableError):
    code = "reference_data_unavailable"
    title = "No reference data release is available"


class ReleaseNotFoundError(NotFoundError):
    code = "release_not_found"
    title = "Reference data release not found"


class ReleaseNotUsableError(GisValidationError):
    code = "release_not_usable"
    title = "Reference data release cannot be used"


def require_usable_release(release: ReleaseRow | None, requested: str | None) -> ReleaseRow:
    """The release to read, or an error saying why there is none.

    ``requested`` is the release code the caller asked for; without one, the current release is meant.
    """
    if release is None:
        if requested is None:
            raise ReferenceDataUnavailableError(
                "no current reference data release is configured; an operator must publish one"
            )
        raise ReleaseNotFoundError(
            f"reference data release {requested} not found", extensions={"refDataRelease": requested}
        )
    if release.status not in USABLE_RELEASE_STATUSES:
        raise ReleaseNotUsableError(
            f"reference data release {release.code} is {release.status}; only published releases can be used",
            extensions={"refDataRelease": release.code, "releaseStatus": release.status},
        )
    return release
