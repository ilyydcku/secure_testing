"""Exercise RBAC through real Django sessions and test-only routes."""

from itertools import product
from types import SimpleNamespace

import pytest
from django.http import JsonResponse
from django.test import Client
from django.urls import include, path
from django.views.decorators.http import require_http_methods
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from accounts.permissions import (
    HasBusinessRole, IsAdmin, IsStudent, IsTeacher, has_role, require_role,
)
from accounts.services import create_user


ROLES = ("STUDENT", "TEACHER", "ADMIN")
PASSWORD = "F9!vQ2#sLm7@pX4z"


def django_probe(request):
    return JsonResponse({"executed": True})


def drf_probe(request):
    return Response({"executed": True})


# These routes are enabled only by this module's fixture, never config.urls.
urlpatterns = [path("api/auth/", include("accounts.urls"))]
for role, permission in zip(ROLES, (IsStudent, IsTeacher, IsAdmin)):
    urlpatterns.append(path(
        f"probe/web/{role}/",
        require_http_methods(["GET", "POST"])(require_role(role)(django_probe)),
    ))
    urlpatterns.append(path(
        f"probe/api/{role}/",
        api_view(["GET", "POST"])(
            authentication_classes([SessionAuthentication])(
                permission_classes([permission])(drf_probe)
            )
        ),
    ))


@pytest.fixture(autouse=True)
def test_routes(settings):
    settings.ROOT_URLCONF = __name__


@pytest.fixture
def user(db):
    return create_user(username="rbac-user", password=PASSWORD, role="STUDENT")


def authenticated_client():
    client = Client(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    response = client.post(
        "/api/auth/login/",
        {"username": "rbac-user", "password": PASSWORD},
        content_type="application/json", HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200
    return client


@pytest.mark.parametrize("interface", ["web", "api"])
@pytest.mark.parametrize("role,required", list(product(ROLES, repeat=2)))
def test_role_matrix(user, interface, role, required):
    user.role = role
    user.save(update_fields=["role"])
    response = authenticated_client().get(f"/probe/{interface}/{required}/")
    assert response.status_code == (200 if role == required else 403)
    if role == required:
        assert response.json() == {"executed": True}
    else:
        assert b'"executed"' not in response.content


@pytest.mark.parametrize("interface", ["web", "api"])
@pytest.mark.parametrize("role", ROLES)
def test_anonymous_denied(interface, role):
    response = Client().get(f"/probe/{interface}/{role}/")
    assert response.status_code == 403
    assert "Location" not in response


@pytest.mark.parametrize("interface", ["web", "api"])
@pytest.mark.parametrize("flags", [(True, False), (False, True), (True, True)])
def test_technical_flags_do_not_grant_other_roles(user, interface, flags):
    user.is_staff, user.is_superuser = flags
    user.save(update_fields=["is_staff", "is_superuser"])
    client = authenticated_client()
    assert client.get(f"/probe/{interface}/STUDENT/").status_code == 200
    for role in ("ADMIN", "TEACHER"):
        assert client.get(f"/probe/{interface}/{role}/").status_code == 403


@pytest.mark.parametrize("interface", ["web", "api"])
def test_role_change_applies_to_existing_session(user, interface):
    client = authenticated_client()
    assert client.get(f"/probe/{interface}/STUDENT/").status_code == 200
    user.role = "TEACHER"
    user.save(update_fields=["role"])
    assert client.get(f"/probe/{interface}/STUDENT/").status_code == 403
    assert client.get(f"/probe/{interface}/TEACHER/").status_code == 200
    assert client.get(f"/probe/{interface}/ADMIN/").status_code == 403


@pytest.mark.parametrize("interface", ["web", "api"])
def test_deactivation_denies_existing_session(user, interface):
    client = authenticated_client()
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert client.get(f"/probe/{interface}/STUDENT/").status_code == 403


@pytest.mark.parametrize("interface", ["web", "api"])
def test_role_permission_does_not_bypass_csrf(user, interface):
    client = authenticated_client()
    url = f"/probe/{interface}/STUDENT/"
    assert client.post(url).status_code == 403
    assert client.post(url, HTTP_X_CSRFTOKEN="invalid").status_code == 403
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    assert client.post(url, HTTP_X_CSRFTOKEN=token).status_code == 200
    assert client.post(
        f"/probe/{interface}/ADMIN/", HTTP_X_CSRFTOKEN=token,
    ).status_code == 403


@pytest.mark.parametrize("role,active", [("UNKNOWN", True), ("ADMIN", False)])
def test_shared_check_fails_closed(role, active):
    user = SimpleNamespace(
        is_authenticated=True, is_active=active, role=role,
        is_staff=True, is_superuser=True,
    )
    assert all(not has_role(user, required) for required in ROLES)
    assert not has_role(user, "UNKNOWN")


def test_unconfigured_permission_fails_closed():
    user = SimpleNamespace(is_authenticated=True, is_active=True, role="ADMIN")
    assert not HasBusinessRole().has_permission(SimpleNamespace(user=user), None)


def test_decorator_rejects_unknown_role():
    with pytest.raises(ValueError, match="Unknown business role"):
        require_role("UNKNOWN")
