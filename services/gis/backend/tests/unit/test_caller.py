"""The caller of a request (``app.core.caller``): the main platform, acting for one tenant."""

from __future__ import annotations

import pytest

from app.core.access import PLATFORM_PERMISSIONS, Permission
from app.core.caller import PLATFORM_SUBJECT, Principal, platform_caller
from app.core.errors import PermissionDeniedError
from app.core.tenancy import TenantId


def test_the_platform_acts_for_one_tenant_with_every_permission_there() -> None:
    caller = platform_caller("dialog-smart-alerts")
    assert caller.subject == PLATFORM_SUBJECT
    assert caller.tenants == {"dialog-smart-alerts"}
    assert caller.permissions == PLATFORM_PERMISSIONS
    assert not caller.all_tenants
    caller.require(*PLATFORM_PERMISSIONS)


def test_a_tenant_the_request_does_not_act_for_is_refused() -> None:
    caller = platform_caller("tenant-a")
    assert caller.require_tenant("tenant-a") == TenantId("tenant-a")
    with pytest.raises(PermissionDeniedError) as info:
        caller.require_tenant("tenant-b")
    assert info.value.status_code == 403
    assert info.value.extensions == {"tenantId": "tenant-b"}


def test_a_permission_the_caller_lacks_is_refused() -> None:
    caller = Principal(
        subject="s", tenants=frozenset({"tenant-a"}), permissions=frozenset({Permission.MAP_READ})
    )
    caller.require(Permission.MAP_READ)
    with pytest.raises(PermissionDeniedError) as info:
        caller.require(Permission.MAP_READ, Permission.DATA_EXPORT)
    assert info.value.extensions == {"requiredPermission": "data:export"}


def test_a_caller_with_every_tenant_may_name_any() -> None:
    caller = Principal(subject="s", tenants=frozenset(), permissions=frozenset({Permission.ALL_TENANTS}))
    assert caller.all_tenants
    assert caller.require_tenant("tenant-z") == TenantId("tenant-z")
