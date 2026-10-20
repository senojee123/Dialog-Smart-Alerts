"""Errors of the reference data pipeline (reported by the CLI as JSON, like the API's problems)."""

from __future__ import annotations

from app.core.errors import GisError


class PipelineError(GisError):
    status_code = 422
    code = "pipeline_failed"
    title = "The reference data pipeline failed"


class ProfileError(PipelineError):
    code = "invalid_profile"
    title = "The pipeline profile is invalid"


class LicenceError(PipelineError):
    code = "licence_not_permitted"
    title = "A source's licence does not permit this use"


class SourceError(PipelineError):
    code = "source_unavailable"
    title = "A source file is missing or does not match"


class CrsError(PipelineError):
    code = "crs_inconsistent"
    title = "The coordinate reference system of a source is unknown or inconsistent"


class FileQaError(PipelineError):
    code = "file_qa_failed"
    title = "A pipeline output failed its QA checks"
