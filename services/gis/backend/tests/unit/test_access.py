"""Permissions and the access context (``app.core.access``)."""

from __future__ import annotations

import pytest

from app.core.access import PLATFORM_PERMISSIONS, Access, Actor, Permission
from app.core.errors import TenantRequiredError
from app.core.tenancy import TenantId


def test_a_request_may_do_everything_within_its_tenant_but_not_act_for_others() -> None:
    """The main platform owns sign-in and roles; the GIS grants every request the same permissions."""
    assert frozenset(Permission) - PLATFORM_PERMISSIONS == {Permission.ALL_TENANTS}


def test_an_actor_is_written_as_client_and_subject() -> None:
    assert Actor("sub-1", "gis-web").label == "gis-web:sub-1"
    assert Actor("sub-1").label == "sub-1"


def test_access_requires_a_tenant_for_tenant_data() -> None:
    tenant = TenantId("tenant-a")
    assert Access(Actor("s"), tenant).required_tenant() == tenant
    with pytest.raises(TenantRequiredError) as info:
        Access(Actor("s"), None).required_tenant("layer needs a tenant", {"layer": "ops.site"})
    assert info.value.extensions == {"layer": "ops.site"}
    assert info.value.status_code == 400


def test_tools_act_as_a_named_operator() -> None:
    access = Access.system("data-steward")
    assert (access.actor.subject, access.actor.channel, access.tenant, access.cross_tenant) == (
        "data-steward",
        "loader",
        None,
        False,
    )
