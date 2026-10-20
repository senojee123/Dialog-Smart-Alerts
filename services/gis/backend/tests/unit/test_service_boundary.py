"""The GIS-only boundary (ADR-0012), checked in the code itself.

The service sends no alerts, orchestrates no notifications, looks up no recipients, stores no
notification locations and delivers nothing by SMS, push or e-mail. Other tests check the database
schema (``test_spatial_model``, ``test_privacy``), the OpenAPI document (``test_spatial_query_api``) and
the map client's source (``frontend/src/map/boundary.test.ts``). This one reads every Python identifier
of the backend, the migrations and the pipeline tools - names of modules, classes, functions, variables,
attributes and keyword arguments, not comments or docstrings, which may say what the service does *not*
do - and the declared dependencies.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path
from typing import Final

import pytest

from app.core.config import REPOSITORY_ROOT

FORBIDDEN_IDENTIFIER: Final = re.compile(
    r"alert|notif|recipient|subscriber|subscription|sms|push_?token|e_?mail_?(address|to)|whatsapp"
    r"|smtp|send_?e_?mail|send_?push|mail_?to|webhook|fcm|apns",
    re.IGNORECASE,
)
# Standard-library and third-party modules that deliver messages. `email` builds messages to send.
FORBIDDEN_IMPORT: Final = re.compile(
    r"^\s*(?:import|from)\s+(smtplib|email|twilio|sendgrid|firebase_admin|pyfcm|apns2|slack_sdk|telegram)\b",
    re.MULTILINE,
)
# Messaging and delivery libraries a GIS service has no use for.
FORBIDDEN_DEPENDENCIES: Final = re.compile(
    r"twilio|sendgrid|firebase|smtp|apns|pyfcm|onesignal|vonage|nexmo|pusher|africastalking|mailgun",
    re.IGNORECASE,
)
SOURCES: Final = (
    REPOSITORY_ROOT / "backend" / "app",
    REPOSITORY_ROOT / "db" / "migrations",
    REPOSITORY_ROOT / "db" / "tools",
    REPOSITORY_ROOT / "data" / "pipeline",
)


def python_files() -> list[Path]:
    return sorted(path for root in SOURCES for path in root.rglob("*.py"))


def identifiers(path: Path) -> set[str]:
    tokens = tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
    return {token.string for token in tokens if token.type == tokenize.NAME}


def test_the_sources_are_found() -> None:
    files = python_files()
    assert len(files) > 50
    assert any(path.name == "seed_dev_data.py" for path in files)


@pytest.mark.parametrize("path", python_files(), ids=lambda path: str(path.relative_to(REPOSITORY_ROOT)))
def test_no_identifier_is_about_alerts_notifications_or_recipients(path: Path) -> None:
    offending = sorted(name for name in identifiers(path) if FORBIDDEN_IDENTIFIER.search(name))
    assert offending == [], f"{path}: {offending} - the GIS service has no alerting responsibilities"


@pytest.mark.parametrize("path", python_files(), ids=lambda path: str(path.relative_to(REPOSITORY_ROOT)))
def test_no_module_imports_a_message_delivery_library(path: Path) -> None:
    imported = FORBIDDEN_IMPORT.findall(path.read_text(encoding="utf-8"))
    assert imported == [], f"{path}: imports {imported} - the GIS service delivers no messages"


def test_the_checks_recognise_what_they_forbid() -> None:
    for name in ("send_alert", "notify_rangers", "recipient_ids", "send_email", "smtp_host", "fcm_token"):
        assert FORBIDDEN_IDENTIFIER.search(name), name
    for name in ("geofence_hits", "nearest_settlement", "admin_area", "event_location", "release_id"):
        assert not FORBIDDEN_IDENTIFIER.search(name), name
    assert FORBIDDEN_IMPORT.findall("import smtplib\nfrom email.message import EmailMessage\n") == [
        "smtplib",
        "email",
    ]


def test_no_file_or_module_is_named_after_alerts_or_notifications() -> None:
    names = [path for root in SOURCES for path in root.rglob("*") if FORBIDDEN_IDENTIFIER.search(path.name)]
    assert names == []


def test_no_messaging_or_delivery_dependency_is_declared() -> None:
    declared = [
        REPOSITORY_ROOT / "backend" / "pyproject.toml",
        *sorted((REPOSITORY_ROOT / "backend").glob("requirements*.lock")),
        REPOSITORY_ROOT / "frontend" / "package.json",
    ]
    for path in declared:
        found = FORBIDDEN_DEPENDENCIES.findall(path.read_text(encoding="utf-8"))
        assert found == [], f"{path.name} declares {found}"
