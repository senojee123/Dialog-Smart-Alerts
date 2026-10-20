"""Reference data pipeline: dataset lineage, licence review, QA results, release artifacts, publish gate.

What a reference data release must be able to answer, recorded by the database (plan §5.4, ADR-0018):

* **Lineage of every dataset** (``meta.dataset_load``, one row per file loaded into a release): the
  source and the exact file or delivery (``source_reference``, ``source_version``, checksum, when it was
  retrieved), the **licence as it was when the data was imported** (snapshot of ``meta.data_source``:
  a later change of a source's terms does not rewrite the history of published releases), the source CRS,
  the storage CRS and the coordinate operation between them, the geometry types and extent actually
  loaded, the nominal accuracy, the tool versions, and the QA expectations the data was checked against.
  ``meta.dataset_lineage`` joins it all per dataset.
* **Licence review** (``meta.data_source.licence_review_*``): a source is ``unreviewed`` until someone
  records an approval (who, when, reference) or a rejection. A *production* release can only be
  published when every dataset in it has an approved licence that permits commercial use (or a recorded
  permission). ``redistribution_allowed`` says whether the data may leave the platform (exports).
* **Release purpose** (``meta.ref_data_release.purpose``): ``production``, ``development`` or ``test``.
  Development and test releases may contain open development data and labelled placeholders; production
  releases may not (enforced by the QA checks, which block publication).
* **QA results** (``meta.qa_run``, ``meta.qa_finding``): the checks run on the files (by the pipeline,
  stage ``file``) and on the loaded release (stage ``database``: ST_IsValid, CRS, duplicates, missing
  identifiers, outliers, extents, topology, licences). A finding marks the check, severity, feature and
  location. An error may be *waived* by an operator with a reason (recorded and audited) unless the check
  forbids it (licences, CRS, invalid geometry).
* **Release artifacts** (``meta.release_artifact``): files built for a release that are not tables, such
  as the basemap (PMTiles and style), with checksum, CRS, zoom range, bounds and their sources and
  licences (``meta.release_artifact_source``).

**Publish gate.** ``meta.guard_release_transition`` now refuses to publish a release unless its latest
database QA run finished after the last change to the release (compared by ``meta.release_fingerprint``)
and left no unwaived errors, and - for a production release - every dataset and artifact source has an
approved licence that permits commercial use. So nothing reaches the API without having passed QA, and
this cannot be bypassed by updating the status column directly.

Like the release itself, QA runs, findings and artifacts are immutable once the release is published.

Revision ID: 20260924_0008
Revises: 20260923_0007
Create Date: 2026-09-24 00:00:00+00:00
"""

# SQL here is composed from constants defined in this module (table names, licence lists, trigger
# bodies); nothing comes from input, so string-built statements are safe.
# ruff: noqa: S608

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from migration_support import (
    comment_columns,
    comment_table,
    literal,
    refuse_if_not_empty,
)

revision: str = "20260924_0008"
down_revision: str | Sequence[str] | None = "20260923_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REFERENCE_TABLES = (
    "admin_area",
    "settlement",
    "facility",
    "road",
    "water_body",
    "protected_area",
    "risk_zone",
)
PURPOSES = ("production", "development", "test")
REVIEW_STATUSES = ("unreviewed", "approved", "rejected")
QA_STAGES = ("file", "database")
QA_STATUSES = ("running", "passed", "warnings", "failed")
SEVERITIES = ("error", "warning", "info")
ARTIFACT_KINDS = ("basemap_tiles", "basemap_style", "basemap_glyphs")
# Licences whose terms let data be copied onward (with attribution / share-alike). Used once, to fill
# redistribution_allowed for sources registered before this revision; anything else becomes false.
REDISTRIBUTABLE_LICENCES = (
    "ODbL-1.0",
    "CC0-1.0",
    "public-domain",
    "CC-BY-4.0",
    "CC-BY-3.0",
    "CC-BY-3.0-IGO",
    "CC-BY-SA-4.0",
    "OGL-UK-3.0",
)
NOT_RECORDED = "not recorded (loaded before revision 20260924_0008)"
CHECK_CODE_PATTERN = r"^[a-z][a-z0-9_]*([.][a-z][a-z0-9_]*)+$"
SHA256_PATTERN = "^[0-9a-f]{64}$"
CRS_PATTERN = "^(EPSG:[0-9]{4,6}|OGC:CRS84)$"


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(literal(value) for value in values) + ")"


# --- sources: licence review and redistribution ------------------------------------------------------


def _data_source() -> None:
    op.execute(
        """
        ALTER TABLE meta.data_source
            ADD COLUMN redistribution_allowed boolean,
            ADD COLUMN licence_review_status text NOT NULL DEFAULT 'unreviewed',
            ADD COLUMN licence_reviewed_by text,
            ADD COLUMN licence_reviewed_on date,
            ADD COLUMN licence_review_reference text
        """
    )
    op.execute(
        f"UPDATE meta.data_source SET redistribution_allowed = licence IN {_in(REDISTRIBUTABLE_LICENCES)}"
    )
    op.execute("ALTER TABLE meta.data_source ALTER COLUMN redistribution_allowed SET NOT NULL")
    op.execute(
        f"""
        ALTER TABLE meta.data_source
            ADD CONSTRAINT ck_data_source_licence_review_status
                CHECK (licence_review_status IN {_in(REVIEW_STATUSES)}),
            ADD CONSTRAINT ck_data_source_licence_review_recorded CHECK (
                licence_review_status = 'unreviewed'
                OR (licence_reviewed_by IS NOT NULL AND licence_reviewed_on IS NOT NULL
                    AND licence_review_reference IS NOT NULL)
            ),
            ADD CONSTRAINT ck_data_source_licence_not_blank CHECK (btrim(licence) <> ''),
            ADD CONSTRAINT ck_data_source_attribution_not_blank CHECK (btrim(attribution) <> '')
        """
    )
    comment_columns(
        "meta.data_source",
        {
            "redistribution_allowed": "Whether the licence lets the data leave the platform (exports, "
            "downloads). False blocks exports of layers built from it.",
            "licence_review_status": "unreviewed, approved or rejected. Production releases need approved "
            "licences; nothing is assumed.",
            "licence_reviewed_by": "Who reviewed the licence for the intended deployment.",
            "licence_reviewed_on": "When the review was recorded.",
            "licence_review_reference": "Legal memo, ticket or agreement the review refers to.",
        },
    )


def _release() -> None:
    op.execute(
        f"""
        ALTER TABLE meta.ref_data_release
            ADD COLUMN purpose text NOT NULL DEFAULT 'development',
            ADD CONSTRAINT ck_ref_data_release_purpose CHECK (purpose IN {_in(PURPOSES)})
        """
    )
    comment_columns(
        "meta.ref_data_release",
        {
            "purpose": "production, development or test. Only production releases are checked for "
            "approved licences and the absence of placeholder data; the pipeline refuses to make a "
            "non-production release current in a production environment.",
        },
    )


# --- dataset lineage ---------------------------------------------------------------------------------


def _dataset_load() -> None:
    op.execute(
        """
        ALTER TABLE meta.dataset_load
            ADD COLUMN source_reference text,
            ADD COLUMN source_retrieved_at timestamptz,
            ADD COLUMN original_file text,
            ADD COLUMN original_checksum_sha256 text,
            ADD COLUMN licence text,
            ADD COLUMN licence_url text,
            ADD COLUMN attribution text,
            ADD COLUMN commercial_use_allowed boolean,
            ADD COLUMN redistribution_allowed boolean,
            ADD COLUMN share_alike boolean,
            ADD COLUMN permission_reference text,
            ADD COLUMN licence_review_status text,
            ADD COLUMN storage_crs text NOT NULL DEFAULT 'EPSG:4326',
            ADD COLUMN coordinate_operation text,
            ADD COLUMN geometry_accuracy_m numeric(10, 2),
            ADD COLUMN geometry_types text[],
            ADD COLUMN extent public.geometry(Polygon, 4326),
            ADD COLUMN qa_expectations jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN tool_versions jsonb NOT NULL DEFAULT '{}'::jsonb
        """
    )
    # Fill the new lineage of loads made before this revision. Rows of published releases are
    # write-protected by a trigger; this one-off backfill lifts it inside the migration transaction.
    op.execute("ALTER TABLE meta.dataset_load DISABLE TRIGGER a10_guard_release_is_draft")
    op.execute(
        f"""
        UPDATE meta.dataset_load AS d
        SET source_reference = coalesce(s.url, {literal(NOT_RECORDED)}),
            licence = s.licence,
            licence_url = s.licence_url,
            attribution = s.attribution,
            commercial_use_allowed = s.commercial_use_allowed,
            redistribution_allowed = s.redistribution_allowed,
            share_alike = s.share_alike,
            permission_reference = s.permission_reference,
            licence_review_status = s.licence_review_status
        FROM meta.data_source AS s
        WHERE s.id = d.source_id
        """
    )
    for table in REFERENCE_TABLES:
        # Table names come from the constant above.
        op.execute(
            f"""
            UPDATE meta.dataset_load AS d
            SET geometry_types = x.types, extent = x.extent, geometry_accuracy_m = x.accuracy
            FROM (
                SELECT f.load_id,
                       array_agg(DISTINCT public.GeometryType(f.geom) ORDER BY public.GeometryType(f.geom))
                           AS types,
                       meta.box_polygon(public.ST_3DExtent(f.geom)) AS extent,
                       max(f.geometry_accuracy_m) AS accuracy
                FROM ref.{table} AS f
                GROUP BY f.load_id
            ) AS x
            WHERE x.load_id = d.id
            """
        )
    op.execute(
        "UPDATE meta.dataset_load SET geometry_types = '{}'::text[] "
        "WHERE geometry_types IS NULL AND status <> 'running'"
    )
    op.execute("ALTER TABLE meta.dataset_load ENABLE TRIGGER a10_guard_release_is_draft")
    op.execute(
        """
        ALTER TABLE meta.dataset_load
            ALTER COLUMN source_reference SET NOT NULL,
            ALTER COLUMN licence SET NOT NULL,
            ALTER COLUMN attribution SET NOT NULL,
            ALTER COLUMN commercial_use_allowed SET NOT NULL,
            ALTER COLUMN redistribution_allowed SET NOT NULL,
            ALTER COLUMN share_alike SET NOT NULL,
            ALTER COLUMN licence_review_status SET NOT NULL
        """
    )
    op.execute(
        f"""
        ALTER TABLE meta.dataset_load
            ADD CONSTRAINT ck_dataset_load_source_reference_not_blank CHECK (btrim(source_reference) <> ''),
            ADD CONSTRAINT ck_dataset_load_original_checksum_format
                CHECK (original_checksum_sha256 ~ '{SHA256_PATTERN}'),
            ADD CONSTRAINT ck_dataset_load_licence_not_blank CHECK (btrim(licence) <> ''),
            ADD CONSTRAINT ck_dataset_load_attribution_not_blank CHECK (btrim(attribution) <> ''),
            ADD CONSTRAINT ck_dataset_load_licence_review_status
                CHECK (licence_review_status IN {_in(REVIEW_STATUSES)}),
            ADD CONSTRAINT ck_dataset_load_source_crs_format CHECK (source_crs ~ '{CRS_PATTERN}'),
            ADD CONSTRAINT ck_dataset_load_storage_crs CHECK (storage_crs = 'EPSG:4326'),
            ADD CONSTRAINT ck_dataset_load_coordinate_operation_recorded
                CHECK (source_crs = storage_crs OR coordinate_operation IS NOT NULL),
            ADD CONSTRAINT ck_dataset_load_geometry_accuracy_m CHECK (geometry_accuracy_m > 0),
            ADD CONSTRAINT ck_dataset_load_geometry_summary
                CHECK (status = 'running' OR geometry_types IS NOT NULL),
            ADD CONSTRAINT ck_dataset_load_qa_expectations_is_object
                CHECK (jsonb_typeof(qa_expectations) = 'object'),
            ADD CONSTRAINT ck_dataset_load_tool_versions_is_object
                CHECK (jsonb_typeof(tool_versions) = 'object')
        """
    )
    comment_columns(
        "meta.dataset_load",
        {
            "source_reference": "URL or reference of the exact file or delivery that was loaded.",
            "source_retrieved_at": "When that file was downloaded or received.",
            "original_file": "Name of the file as received from the source, before the pipeline processed it "
            "(source_file is the GIS-ready file that was loaded).",
            "original_checksum_sha256": "SHA-256 of the file as received from the source.",
            "licence": "Licence of the source at the time of the load (snapshot of meta.data_source).",
            "licence_url": "Licence text, at the time of the load.",
            "attribution": "Attribution required by the source, at the time of the load.",
            "commercial_use_allowed": "Snapshot: whether the licence permits commercial use.",
            "redistribution_allowed": "Snapshot: whether the data may leave the platform (exports).",
            "share_alike": "Snapshot: whether derived databases must be offered under the same licence.",
            "permission_reference": "Snapshot: written permission covering uses the licence does not.",
            "licence_review_status": "Snapshot: licence review status (unreviewed, approved, rejected).",
            "storage_crs": "CRS of the stored geometry (always EPSG:4326).",
            "coordinate_operation": "PROJ pipeline or EPSG operation used from source_crs to storage_crs.",
            "geometry_accuracy_m": "Nominal horizontal accuracy of the dataset in metres.",
            "geometry_types": "Geometry types of the rows loaded (e.g. {MULTIPOLYGON}).",
            "extent": "Bounding box of the rows loaded.",
            "qa_expectations": "What the QA checks expect of this dataset (extent, counts, tolerances).",
            "tool_versions": "Versions of the pipeline tools that produced the file (GDAL, PROJ, ...).",
        },
    )


# --- QA ----------------------------------------------------------------------------------------------


def _qa_tables() -> None:
    op.execute(
        f"""
        CREATE TABLE meta.qa_run (
            id uuid NOT NULL DEFAULT uuidv7(),
            release_id uuid NOT NULL,
            load_id uuid,
            stage text NOT NULL,
            status text NOT NULL DEFAULT 'running',
            content_fingerprint text,
            check_count integer NOT NULL DEFAULT 0,
            error_count integer NOT NULL DEFAULT 0,
            warning_count integer NOT NULL DEFAULT 0,
            info_count integer NOT NULL DEFAULT 0,
            parameters jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            tool_version text NOT NULL,
            started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            finished_at timestamptz,
            run_by text NOT NULL DEFAULT session_user,
            CONSTRAINT pk_qa_run PRIMARY KEY (id),
            CONSTRAINT uq_qa_run_id_release_id UNIQUE (id, release_id),
            CONSTRAINT fk_qa_run_release_id_ref_data_release FOREIGN KEY (release_id)
                REFERENCES meta.ref_data_release (id) ON DELETE CASCADE,
            CONSTRAINT fk_qa_run_load_id_release_id_dataset_load FOREIGN KEY (load_id, release_id)
                REFERENCES meta.dataset_load (id, release_id) ON DELETE CASCADE,
            CONSTRAINT ck_qa_run_stage CHECK (stage IN {_in(QA_STAGES)}),
            CONSTRAINT ck_qa_run_stage_scope CHECK ((stage = 'file') = (load_id IS NOT NULL)),
            CONSTRAINT ck_qa_run_status CHECK (status IN {_in(QA_STATUSES)}),
            CONSTRAINT ck_qa_run_finished_at CHECK (
                (status = 'running') = (finished_at IS NULL)
                AND (finished_at IS NULL OR finished_at >= started_at)
            ),
            CONSTRAINT ck_qa_run_counts CHECK (
                check_count >= 0 AND error_count >= 0 AND warning_count >= 0 AND info_count >= 0
            ),
            CONSTRAINT ck_qa_run_database_fingerprint
                CHECK (stage = 'file' OR status = 'running' OR content_fingerprint IS NOT NULL),
            CONSTRAINT ck_qa_run_parameters_is_object CHECK (jsonb_typeof(parameters) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_qa_run_release_id_stage_started_at ON meta.qa_run (release_id, stage, started_at)"
    )
    op.execute("CREATE INDEX ix_qa_run_load_id ON meta.qa_run (load_id)")
    comment_table(
        "meta.qa_run",
        "One run of the reference data QA checks: on a pipeline output file (stage file, per dataset load) "
        "or on the loaded release (stage database). A release is published only after a database run "
        "that saw its final content and left no unwaived errors.",
    )
    comment_columns(
        "meta.qa_run",
        {
            "stage": "file (checked by the pipeline before loading) or database (checked in PostGIS).",
            "status": "running, passed, warnings or failed (errors found).",
            "content_fingerprint": "meta.release_fingerprint() of the release when the run finished; "
            "publishing requires it to be unchanged.",
            "parameters": "Checks and thresholds the run used.",
            "tool_version": "Version of the code that ran the checks.",
        },
    )

    op.execute(
        f"""
        CREATE TABLE meta.qa_finding (
            id bigint GENERATED ALWAYS AS IDENTITY,
            run_id uuid NOT NULL,
            release_id uuid NOT NULL,
            check_code text NOT NULL,
            severity text NOT NULL,
            layer_code text,
            load_id uuid,
            feature_id uuid,
            source_feature_id text,
            message text NOT NULL,
            details jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            location public.geometry(Geometry, 4326),
            waivable boolean NOT NULL DEFAULT true,
            waived_at timestamptz,
            waived_by text,
            waiver_reason text,
            CONSTRAINT pk_qa_finding PRIMARY KEY (id),
            CONSTRAINT fk_qa_finding_run_id_release_id_qa_run FOREIGN KEY (run_id, release_id)
                REFERENCES meta.qa_run (id, release_id) ON DELETE CASCADE,
            CONSTRAINT ck_qa_finding_check_code_format CHECK (check_code ~ '{CHECK_CODE_PATTERN}'),
            CONSTRAINT ck_qa_finding_severity CHECK (severity IN {_in(SEVERITIES)}),
            CONSTRAINT ck_qa_finding_message_not_blank CHECK (btrim(message) <> ''),
            CONSTRAINT ck_qa_finding_details_is_object CHECK (jsonb_typeof(details) = 'object'),
            CONSTRAINT ck_qa_finding_waiver_complete CHECK (
                (waived_at IS NULL) = (waived_by IS NULL) AND (waived_at IS NULL) = (waiver_reason IS NULL)
            ),
            CONSTRAINT ck_qa_finding_waiver_reason_not_blank CHECK (btrim(waiver_reason) <> ''),
            CONSTRAINT ck_qa_finding_waivable CHECK (waivable OR waived_at IS NULL)
        )
        """
    )
    op.execute("CREATE INDEX ix_qa_finding_run_id_severity ON meta.qa_finding (run_id, severity)")
    op.execute("CREATE INDEX ix_qa_finding_release_id ON meta.qa_finding (release_id)")
    comment_table(
        "meta.qa_finding",
        "A problem found by a QA run: check, severity (error blocks publication), layer, feature and "
        "location. Only the waiver columns can change, and only while the release is a draft.",
    )
    comment_columns(
        "meta.qa_finding",
        {
            "check_code": "Check that found it, e.g. geometry.invalid, topology.admin_sibling_overlap.",
            "severity": "error (blocks publication unless waived), warning or info.",
            "location": "Where the problem is (a point, or the offending geometry part), EPSG:4326.",
            "waivable": "False for checks that cannot be accepted (licences, CRS, invalid geometry).",
            "waived_by": "Actor who accepted the error (from gis.actor_subject, else the login).",
            "waiver_reason": "Why the error is acceptable for this release.",
        },
    )


def _qa_functions() -> None:
    fingerprint_parts = ",\n            ".join(
        f"(SELECT count(*) || ':' || coalesce(extract(epoch FROM max(t.updated_at))::text, '') || ':' "
        f"|| coalesce(extract(epoch FROM max(t.created_at))::text, '') FROM ref.{table} AS t "
        "WHERE t.release_id = r)"
        for table in REFERENCE_TABLES
    )
    op.execute(
        f"""
        CREATE FUNCTION meta.release_fingerprint(r uuid)
        RETURNS text
        LANGUAGE sql STABLE PARALLEL SAFE
        RETURN md5(concat_ws('|',
            (SELECT string_agg(concat_ws(':', l.id, l.status, l.loaded_count, l.repaired_count,
                                         l.rejected_count, extract(epoch FROM l.finished_at)), ','
                               ORDER BY l.id)
             FROM meta.dataset_load AS l WHERE l.release_id = r),
            (SELECT string_agg(concat_ws(':', a.id, a.sha256), ',' ORDER BY a.id)
             FROM meta.release_artifact AS a WHERE a.release_id = r),
            {fingerprint_parts}))
        """
    )
    op.execute(
        "COMMENT ON FUNCTION meta.release_fingerprint(uuid) IS "
        "'Digest of what a release contains (loads, artifacts, row counts and last changes per layer; "
        "independent of the session time zone). "
        "A QA run records it; publishing compares it, so data changed after QA cannot be published.'"
    )
    op.execute(
        """
        CREATE FUNCTION meta.guard_qa_finding_waiver()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF (NEW.run_id, NEW.release_id, NEW.check_code, NEW.severity, NEW.layer_code, NEW.load_id,
                NEW.feature_id, NEW.source_feature_id, NEW.message, NEW.details, NEW.waivable)
                IS DISTINCT FROM
               (OLD.run_id, OLD.release_id, OLD.check_code, OLD.severity, OLD.layer_code, OLD.load_id,
                OLD.feature_id, OLD.source_feature_id, OLD.message, OLD.details, OLD.waivable)
               OR public.ST_AsEWKB(NEW.location) IS DISTINCT FROM public.ST_AsEWKB(OLD.location) THEN
                RAISE EXCEPTION 'QA finding %: only its waiver can be recorded', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.waived_at IS NOT NULL THEN
                RAISE EXCEPTION 'QA finding % is already waived; run the QA checks again to start over',
                    OLD.id USING ERRCODE = '55000';
            END IF;
            IF NEW.waiver_reason IS NULL OR btrim(NEW.waiver_reason) = '' THEN
                RAISE EXCEPTION 'a waiver of QA finding % needs a reason', OLD.id USING ERRCODE = '23514';
            END IF;
            IF NOT OLD.waivable THEN
                RAISE EXCEPTION 'QA check % cannot be waived (finding %)', OLD.check_code, OLD.id
                    USING ERRCODE = '55000';
            END IF;
            -- Who and when come from the transaction, not from the writer.
            NEW.waived_at := now();
            NEW.waived_by := coalesce(nullif(current_setting('gis.actor_subject', true), ''), session_user);
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION audit.record_qa_waiver()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF NEW.waived_at IS NOT NULL AND OLD.waived_at IS NULL THEN
                INSERT INTO audit.entry (category, operation, target, object_id, parameters)
                SELECT 'release', 'reference_release.qa_waiver', 'meta.qa_finding', NEW.id::text,
                       jsonb_strip_nulls(jsonb_build_object(
                           'code', r.code,
                           'check', NEW.check_code,
                           'severity', NEW.severity,
                           'layer', NEW.layer_code,
                           'sourceFeatureId', NEW.source_feature_id,
                           'reason', NEW.waiver_reason))
                FROM meta.ref_data_release AS r
                WHERE r.id = NEW.release_id;
            END IF;
            RETURN NULL;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION audit.record_qa_waiver() FROM PUBLIC")


def _qa_triggers() -> None:
    for table in ("meta.qa_run", "meta.qa_finding"):
        op.execute(
            f"CREATE TRIGGER a10_guard_release_is_draft BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION meta.guard_release_is_draft()"
        )
    op.execute(
        "CREATE TRIGGER a20_guard_waiver BEFORE UPDATE ON meta.qa_finding "
        "FOR EACH ROW EXECUTE FUNCTION meta.guard_qa_finding_waiver()"
    )
    op.execute(
        "CREATE TRIGGER z90_audit_waiver AFTER UPDATE ON meta.qa_finding "
        "FOR EACH ROW EXECUTE FUNCTION audit.record_qa_waiver()"
    )


# --- release artifacts (basemap) --------------------------------------------------------------------


def _artifacts() -> None:
    op.execute(
        f"""
        CREATE TABLE meta.release_artifact (
            id uuid NOT NULL DEFAULT uuidv7(),
            release_id uuid NOT NULL,
            kind text NOT NULL,
            name text NOT NULL,
            uri text NOT NULL,
            media_type text NOT NULL,
            sha256 text NOT NULL,
            size_bytes bigint NOT NULL,
            crs text NOT NULL,
            min_zoom smallint,
            max_zoom smallint,
            bounds public.geometry(Polygon, 4326),
            geometry_types text[] NOT NULL DEFAULT '{{}}'::text[],
            geometry_accuracy_m numeric(10, 2),
            transformation text NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            tool_versions jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by text NOT NULL DEFAULT CURRENT_USER,
            CONSTRAINT pk_release_artifact PRIMARY KEY (id),
            CONSTRAINT uq_release_artifact_id_release_id UNIQUE (id, release_id),
            CONSTRAINT uq_release_artifact_release_id_name UNIQUE (release_id, name),
            CONSTRAINT fk_release_artifact_release_id_ref_data_release FOREIGN KEY (release_id)
                REFERENCES meta.ref_data_release (id) ON DELETE CASCADE,
            CONSTRAINT ck_release_artifact_kind CHECK (kind IN {_in(ARTIFACT_KINDS)}),
            CONSTRAINT ck_release_artifact_name_format CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9._ -]*$'),
            CONSTRAINT ck_release_artifact_uri_not_blank CHECK (btrim(uri) <> ''),
            CONSTRAINT ck_release_artifact_sha256_format CHECK (sha256 ~ '{SHA256_PATTERN}'),
            CONSTRAINT ck_release_artifact_size_bytes CHECK (size_bytes >= 0),
            CONSTRAINT ck_release_artifact_crs_format CHECK (crs ~ '{CRS_PATTERN}'),
            CONSTRAINT ck_release_artifact_zoom CHECK (
                (min_zoom IS NULL OR min_zoom BETWEEN 0 AND 24)
                AND (max_zoom IS NULL OR max_zoom BETWEEN 0 AND 24)
                AND (min_zoom IS NULL OR max_zoom IS NULL OR min_zoom <= max_zoom)
            ),
            CONSTRAINT ck_release_artifact_geometry_accuracy_m CHECK (geometry_accuracy_m > 0),
            CONSTRAINT ck_release_artifact_metadata_is_object CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT ck_release_artifact_tool_versions_is_object
                CHECK (jsonb_typeof(tool_versions) = 'object')
        )
        """
    )
    comment_table(
        "meta.release_artifact",
        "Files built for a reference data release that are not tables: the basemap tiles (PMTiles), its "
        "MapLibre style and glyphs. Served as static files; recorded here with checksum, CRS, zoom range and "
        "bounds so the release describes everything a client shows.",
    )
    comment_columns(
        "meta.release_artifact",
        {
            "kind": "basemap_tiles, basemap_style or basemap_glyphs.",
            "uri": "Where clients fetch it, relative to the basemap root "
            "(e.g. ref-2026.09-dev/basemap.pmtiles).",
            "crs": "CRS of the content: EPSG:3857 for vector tiles.",
            "geometry_types": "Geometry types in the tiles.",
            "metadata": "Tile layers, zoom ranges per layer and other build details.",
        },
    )
    op.execute(
        f"""
        CREATE TABLE meta.release_artifact_source (
            artifact_id uuid NOT NULL,
            release_id uuid NOT NULL,
            source_id uuid NOT NULL,
            role text NOT NULL,
            source_version text,
            source_reference text NOT NULL,
            source_checksum_sha256 text,
            source_retrieved_at timestamptz,
            licence text NOT NULL,
            licence_url text,
            attribution text NOT NULL,
            commercial_use_allowed boolean NOT NULL,
            redistribution_allowed boolean NOT NULL,
            share_alike boolean NOT NULL,
            permission_reference text,
            licence_review_status text NOT NULL,
            CONSTRAINT pk_release_artifact_source PRIMARY KEY (artifact_id, source_id),
            CONSTRAINT fk_release_artifact_source_artifact_id_release_id_release_artifact
                FOREIGN KEY (artifact_id, release_id)
                REFERENCES meta.release_artifact (id, release_id) ON DELETE CASCADE,
            CONSTRAINT fk_release_artifact_source_source_id_data_source FOREIGN KEY (source_id)
                REFERENCES meta.data_source (id) ON DELETE RESTRICT,
            CONSTRAINT ck_release_artifact_source_role_not_blank CHECK (btrim(role) <> ''),
            CONSTRAINT ck_release_artifact_source_checksum_format
                CHECK (source_checksum_sha256 ~ '{SHA256_PATTERN}'),
            CONSTRAINT ck_release_artifact_source_licence_review_status
                CHECK (licence_review_status IN {_in(REVIEW_STATUSES)})
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_release_artifact_source_source_id ON meta.release_artifact_source (source_id)"
    )
    comment_table(
        "meta.release_artifact_source",
        "Sources an artifact was built from, with the licence as it was when the artifact was built.",
    )
    comment_columns(
        "meta.release_artifact_source",
        {"role": "What was taken from the source (e.g. roads, land)."},
    )
    for table in ("meta.release_artifact", "meta.release_artifact_source"):
        op.execute(
            f"CREATE TRIGGER a10_guard_release_is_draft BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION meta.guard_release_is_draft()"
        )


# --- lineage view ------------------------------------------------------------------------------------


def _lineage_view() -> None:
    op.execute(
        """
        CREATE VIEW meta.dataset_lineage WITH (security_invoker = true) AS
        SELECT r.id AS release_id,
               r.code AS release_code,
               r.status AS release_status,
               r.purpose AS release_purpose,
               y.code AS layer_code,
               y.name AS layer_name,
               l.id AS load_id,
               s.code AS source_code,
               s.name AS source_name,
               s.publisher,
               l.licence,
               l.licence_url,
               l.attribution,
               l.commercial_use_allowed,
               l.redistribution_allowed,
               l.share_alike,
               l.permission_reference,
               l.licence_review_status,
               l.source_reference,
               l.source_version,
               l.source_file,
               l.source_checksum_sha256,
               l.source_retrieved_at,
               l.original_file,
               l.original_checksum_sha256,
               l.source_crs,
               l.storage_crs,
               l.coordinate_operation,
               l.transformation,
               l.geometry_types,
               l.geometry_accuracy_m,
               l.extent,
               l.source_feature_count,
               l.loaded_count,
               l.repaired_count,
               l.rejected_count,
               l.status AS load_status,
               l.started_at AS imported_at,
               l.finished_at,
               l.loaded_by,
               l.loader_version,
               l.tool_versions
        FROM meta.dataset_load AS l
        JOIN meta.ref_data_release AS r ON r.id = l.release_id
        JOIN meta.layer AS y ON y.id = l.layer_id
        JOIN meta.data_source AS s ON s.id = l.source_id
        """
    )
    op.execute(
        "COMMENT ON VIEW meta.dataset_lineage IS "
        + literal(
            "Every dataset of every reference data release with its source, licence (as imported), source "
            "reference and version, import time, geometry types, CRS, accuracy and release."
        )
    )


# --- publish gate and release audit ------------------------------------------------------------------

_TRANSITION_PREAMBLE = """
        CREATE OR REPLACE FUNCTION meta.guard_release_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
"""

GUARD_RELEASE_TRANSITION_V2 = (
    _TRANSITION_PREAMBLE
    + """
        DECLARE
            qa_id uuid;
            qa_fingerprint text;
            open_errors bigint;
            unlicensed text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'published' THEN
                    RAISE EXCEPTION 'reference data release % is published; retire it before deleting it',
                        OLD.code
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'draft' THEN
                    RAISE EXCEPTION 'a new reference data release must start as draft'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.code <> OLD.code THEN
                RAISE EXCEPTION 'the code of reference data release % cannot change', OLD.code
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.purpose <> OLD.purpose AND OLD.status <> 'draft' THEN
                RAISE EXCEPTION 'the purpose of reference data release % cannot change after publication',
                    OLD.code
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status <> OLD.status THEN
                IF NOT (OLD.status, NEW.status) IN (('draft', 'published'), ('published', 'retired')) THEN
                    RAISE EXCEPTION 'reference data release % cannot move from % to %',
                        OLD.code, OLD.status, NEW.status
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.status = 'published' THEN
                    IF EXISTS (
                        SELECT 1 FROM meta.dataset_load AS l
                        WHERE l.release_id = NEW.id AND l.status = 'running'
                    ) THEN
                        RAISE EXCEPTION 'reference data release % has loads still running', NEW.code
                            USING ERRCODE = '55000';
                    END IF;
                    -- QA gate: the latest database QA run must have seen exactly this content ...
                    SELECT q.id, q.content_fingerprint INTO qa_id, qa_fingerprint
                    FROM meta.qa_run AS q
                    WHERE q.release_id = NEW.id AND q.stage = 'database' AND q.status <> 'running'
                    ORDER BY q.started_at DESC, q.id DESC
                    LIMIT 1;
                    IF qa_id IS NULL THEN
                        RAISE EXCEPTION 'reference data release % has not been checked; run the QA checks '
                            'before publishing', NEW.code
                            USING ERRCODE = '55000';
                    END IF;
                    IF qa_fingerprint IS DISTINCT FROM meta.release_fingerprint(NEW.id) THEN
                        RAISE EXCEPTION 'reference data release % changed after its last QA run %; run the '
                            'QA checks again', NEW.code, qa_id
                            USING ERRCODE = '55000';
                    END IF;
                    -- ... and left no error that nobody accepted.
                    SELECT count(*) INTO open_errors
                    FROM meta.qa_finding AS f
                    WHERE f.run_id = qa_id AND f.severity = 'error' AND f.waived_at IS NULL;
                    IF open_errors > 0 THEN
                        RAISE EXCEPTION 'reference data release % has % unresolved QA errors (QA run %)',
                            NEW.code, open_errors, qa_id
                            USING ERRCODE = '55000';
                    END IF;
                    -- Licence gate for production: every source reviewed, approved and usable commercially.
                    IF NEW.purpose = 'production' THEN
                        SELECT string_agg(DISTINCT x.label, ', ') INTO unlicensed
                        FROM (
                            SELECT s.code AS label, l.licence_review_status AS review,
                                   l.commercial_use_allowed AS commercial,
                                   l.permission_reference AS permission
                            FROM meta.dataset_load AS l JOIN meta.data_source AS s ON s.id = l.source_id
                            WHERE l.release_id = NEW.id
                            UNION ALL
                            SELECT s.code, a.licence_review_status, a.commercial_use_allowed,
                                   a.permission_reference
                            FROM meta.release_artifact_source AS a
                            JOIN meta.data_source AS s ON s.id = a.source_id
                            WHERE a.release_id = NEW.id
                        ) AS x
                        WHERE x.review <> 'approved' OR NOT (x.commercial OR x.permission IS NOT NULL);
                        IF unlicensed IS NOT NULL THEN
                            RAISE EXCEPTION 'production release % uses sources without an approved licence '
                                'for commercial use: %', NEW.code, unlicensed
                                USING ERRCODE = '55000';
                        END IF;
                    END IF;
                    NEW.published_at := now();
                ELSE
                    NEW.retired_at := now();
                    NEW.is_current := false;
                END IF;
            ELSIF NEW.published_at IS DISTINCT FROM OLD.published_at
                OR NEW.retired_at IS DISTINCT FROM OLD.retired_at THEN
                RAISE EXCEPTION 'publication timestamps of release % are maintained by the database', OLD.code
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$
        """
)

GUARD_RELEASE_TRANSITION_V1 = (
    _TRANSITION_PREAMBLE
    + """
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'published' THEN
                    RAISE EXCEPTION 'reference data release % is published; retire it before deleting it',
                        OLD.code
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'draft' THEN
                    RAISE EXCEPTION 'a new reference data release must start as draft'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.code <> OLD.code THEN
                RAISE EXCEPTION 'the code of reference data release % cannot change', OLD.code
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status <> OLD.status THEN
                IF NOT (OLD.status, NEW.status) IN (('draft', 'published'), ('published', 'retired')) THEN
                    RAISE EXCEPTION 'reference data release % cannot move from % to %',
                        OLD.code, OLD.status, NEW.status
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.status = 'published' THEN
                    IF EXISTS (
                        SELECT 1 FROM meta.dataset_load AS l
                        WHERE l.release_id = NEW.id AND l.status = 'running'
                    ) THEN
                        RAISE EXCEPTION 'reference data release % has loads still running', NEW.code
                            USING ERRCODE = '55000';
                    END IF;
                    NEW.published_at := now();
                ELSE
                    NEW.retired_at := now();
                    NEW.is_current := false;
                END IF;
            ELSIF NEW.published_at IS DISTINCT FROM OLD.published_at
                OR NEW.retired_at IS DISTINCT FROM OLD.retired_at THEN
                RAISE EXCEPTION 'publication timestamps of release % are maintained by the database', OLD.code
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$
        """
)

_RELEASE_AUDIT_HEAD = """
        CREATE OR REPLACE FUNCTION audit.record_release_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            release meta.ref_data_release;
            previous_status text;
            operations text[] := '{}';
            operation text;
            dataset_count bigint;
            feature_count bigint;
            rejected_count bigint;
"""

_RELEASE_AUDIT_OPERATIONS = """
        BEGIN
            IF TG_OP = 'INSERT' THEN
                release := NEW;
                operations := ARRAY['create'];
            ELSIF TG_OP = 'DELETE' THEN
                release := OLD;
                operations := ARRAY['delete'];
            ELSE
                release := NEW;
                previous_status := OLD.status;
                IF NEW.status IS DISTINCT FROM OLD.status THEN
                    operations := operations || CASE NEW.status
                        WHEN 'published' THEN 'publish' WHEN 'retired' THEN 'retire' ELSE 'reopen' END;
                END IF;
                IF NEW.is_current AND NOT OLD.is_current THEN
                    operations := operations || 'make_current'::text;
                ELSIF OLD.is_current AND NOT NEW.is_current THEN
                    operations := operations || 'unset_current'::text;
                END IF;
            END IF;
            IF cardinality(operations) = 0 THEN
                RETURN NULL;  -- a description or timestamp changed: not a lifecycle event
            END IF;
            SELECT count(*), coalesce(sum(d.loaded_count), 0), coalesce(sum(d.rejected_count), 0)
            INTO dataset_count, feature_count, rejected_count
            FROM meta.dataset_load AS d
            WHERE d.release_id = release.id AND d.status = 'completed';
"""

RECORD_RELEASE_CHANGE_V2 = (
    _RELEASE_AUDIT_HEAD
    + """
            qa_id uuid;
            qa_status text;
"""
    + _RELEASE_AUDIT_OPERATIONS
    + """
            IF TG_OP <> 'DELETE' THEN
                SELECT q.id, q.status INTO qa_id, qa_status
                FROM meta.qa_run AS q
                WHERE q.release_id = release.id AND q.stage = 'database' AND q.status <> 'running'
                ORDER BY q.started_at DESC, q.id DESC
                LIMIT 1;
            END IF;
            FOREACH operation IN ARRAY operations LOOP
                INSERT INTO audit.entry (category, operation, target, object_id, parameters, result_count)
                VALUES (
                    'release', 'reference_release.' || operation, 'meta.ref_data_release', release.id::text,
                    jsonb_strip_nulls(jsonb_build_object(
                        'code', release.code,
                        'status', release.status,
                        'purpose', release.purpose,
                        'previousStatus', previous_status,
                        'isCurrent', release.is_current,
                        'datasets', dataset_count,
                        'rejectedFeatures', rejected_count,
                        'qaRun', qa_id,
                        'qaStatus', qa_status)),
                    CASE WHEN operation IN ('publish', 'make_current') THEN feature_count END);
            END LOOP;
            RETURN NULL;
        END
        $$
        """
)

RECORD_RELEASE_CHANGE_V1 = (
    _RELEASE_AUDIT_HEAD
    + _RELEASE_AUDIT_OPERATIONS
    + """
            FOREACH operation IN ARRAY operations LOOP
                INSERT INTO audit.entry (category, operation, target, object_id, parameters, result_count)
                VALUES (
                    'release', 'reference_release.' || operation, 'meta.ref_data_release', release.id::text,
                    jsonb_strip_nulls(jsonb_build_object(
                        'code', release.code,
                        'status', release.status,
                        'previousStatus', previous_status,
                        'isCurrent', release.is_current,
                        'datasets', dataset_count,
                        'rejectedFeatures', rejected_count)),
                    CASE WHEN operation IN ('publish', 'make_current') THEN feature_count END);
            END LOOP;
            RETURN NULL;
        END
        $$
        """
)


def _box_polygon() -> None:
    op.execute(
        """
        CREATE FUNCTION meta.box_polygon(b public.box3d)
        RETURNS public.geometry
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        RETURN public.ST_MakeEnvelope(
            public.ST_XMin(b), public.ST_YMin(b), public.ST_XMax(b), public.ST_YMax(b), 4326)
        """
    )
    op.execute(
        "COMMENT ON FUNCTION meta.box_polygon(public.box3d) IS "
        "'EPSG:4326 polygon of a bounding box (double precision, unlike box2d).'"
    )


def upgrade() -> None:
    _box_polygon()
    _data_source()
    _release()
    _dataset_load()
    _qa_tables()
    _artifacts()
    _qa_functions()
    _qa_triggers()
    _lineage_view()
    op.execute(GUARD_RELEASE_TRANSITION_V2)
    op.execute(RECORD_RELEASE_CHANGE_V2)


def downgrade() -> None:
    # Lineage, licence reviews and QA results are evidence: refuse rather than discard them.
    refuse_if_not_empty(
        [
            "meta.qa_finding",
            "meta.qa_run",
            "meta.release_artifact_source",
            "meta.release_artifact",
            "meta.dataset_load",
        ]
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM meta.data_source WHERE licence_review_status <> 'unreviewed') THEN
                RAISE EXCEPTION 'downgrade refused: meta.data_source holds licence reviews; export them first'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$
        """
    )
    op.execute(RECORD_RELEASE_CHANGE_V1)
    op.execute(GUARD_RELEASE_TRANSITION_V1)
    # The fingerprint's SQL body depends on the tables below.
    op.execute("DROP FUNCTION meta.release_fingerprint(uuid)")
    op.execute("DROP VIEW meta.dataset_lineage")
    op.execute("DROP TRIGGER z90_audit_waiver ON meta.qa_finding")
    op.execute("DROP TABLE meta.release_artifact_source")
    op.execute("DROP TABLE meta.release_artifact")
    op.execute("DROP TABLE meta.qa_finding")
    op.execute("DROP TABLE meta.qa_run")
    op.execute("DROP FUNCTION audit.record_qa_waiver()")
    op.execute("DROP FUNCTION meta.guard_qa_finding_waiver()")
    op.execute(
        """
        ALTER TABLE meta.dataset_load
            DROP CONSTRAINT ck_dataset_load_source_crs_format,
            DROP COLUMN source_reference,
            DROP COLUMN source_retrieved_at,
            DROP COLUMN original_file,
            DROP COLUMN original_checksum_sha256,
            DROP COLUMN licence,
            DROP COLUMN licence_url,
            DROP COLUMN attribution,
            DROP COLUMN commercial_use_allowed,
            DROP COLUMN redistribution_allowed,
            DROP COLUMN share_alike,
            DROP COLUMN permission_reference,
            DROP COLUMN licence_review_status,
            DROP COLUMN storage_crs,
            DROP COLUMN coordinate_operation,
            DROP COLUMN geometry_accuracy_m,
            DROP COLUMN geometry_types,
            DROP COLUMN extent,
            DROP COLUMN qa_expectations,
            DROP COLUMN tool_versions
        """
    )
    op.execute("ALTER TABLE meta.ref_data_release DROP COLUMN purpose")
    op.execute(
        """
        ALTER TABLE meta.data_source
            DROP CONSTRAINT ck_data_source_licence_not_blank,
            DROP CONSTRAINT ck_data_source_attribution_not_blank,
            DROP COLUMN redistribution_allowed,
            DROP COLUMN licence_review_status,
            DROP COLUMN licence_reviewed_by,
            DROP COLUMN licence_reviewed_on,
            DROP COLUMN licence_review_reference
        """
    )
    op.execute("DROP FUNCTION meta.box_polygon(public.box3d)")
