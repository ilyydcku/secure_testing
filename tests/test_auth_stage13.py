"""Stage 13 session authentication and CSRF contract tests."""

import json
import os
import subprocess
import sys
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client, override_settings
from django.utils import timezone

from accounts.services import create_user


pytestmark = pytest.mark.django_db

VALID_PASSWORD = "F9!vQ2#sLm7@pX4z"


@pytest.fixture
def user():
    return create_user(
        username="auth-student", password=VALID_PASSWORD, role="STUDENT"
    )


@pytest.fixture
def csrf_client():
    client = Client(enforce_csrf_checks=True)
    response = client.get("/api/auth/csrf/")
    assert response.status_code == 200
    return client, response.json()["csrfToken"]


def post_login(client, csrf_token, username="auth-student", password=VALID_PASSWORD):
    return client.post(
        "/api/auth/login/",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )


def test_csrf_endpoint_does_not_create_session_or_authenticate(csrf_client):
    client, csrf = csrf_client
    assert csrf
    assert settings.CSRF_COOKIE_NAME in client.cookies
    assert settings.SESSION_COOKIE_NAME not in client.cookies
    assert not Session.objects.exists()
    assert client.get("/api/auth/me/").status_code == 403


def test_login_me_returns_whitelisted_current_user_and_server_session(user, csrf_client):
    client, token = csrf_client
    response = post_login(client, token)
    assert response.status_code == 200
    assert response.json() == {"id": user.pk, "username": user.username, "role": "STUDENT"}

    session_key = client.cookies[settings.SESSION_COOKIE_NAME].value
    assert Session.objects.filter(session_key=session_key).exists()
    assert client.get("/api/auth/me/").json() == response.json()


def test_anonymous_me_is_forbidden_even_with_basic_credentials(user):
    import base64

    credentials = base64.b64encode(f"{user.username}:{VALID_PASSWORD}".encode()).decode()
    client = Client()
    assert client.get("/api/auth/me/").status_code == 403
    response = client.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Basic {credentials}")
    assert response.status_code == 403


@pytest.mark.parametrize("csrf_header", [None, "incorrect-token"])
def test_login_rejects_missing_or_invalid_csrf(user, csrf_client, csrf_header):
    client, _ = csrf_client
    kwargs = {} if csrf_header is None else {"HTTP_X_CSRFTOKEN": csrf_header}
    response = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": user.username, "password": VALID_PASSWORD}),
        content_type="application/json",
        **kwargs,
    )
    assert response.status_code == 403
    assert client.get("/api/auth/me/").status_code == 403


@pytest.mark.parametrize("username,password", [
    ("unknown-user", VALID_PASSWORD),
    ("auth-student", "wrong-password"),
])
def test_invalid_login_has_neutral_401(user, csrf_client, username, password):
    client, token = csrf_client
    response = post_login(client, token, username, password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials."}
    assert client.get("/api/auth/me/").status_code == 403


def test_inactive_account_login_is_same_neutral_401(user, csrf_client):
    client, token = csrf_client
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = post_login(client, token)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials."}


@pytest.mark.parametrize("payload,content_type", [
    ('{"username":', "application/json"),
    ('["auth-student", "password"]', "application/json"),
    ('{"username":"auth-student"}', "application/json"),
    ('{"username":"auth-student","password":42}', "application/json"),
    ('{"username":"auth-student","password":"x","role":"ADMIN"}', "application/json"),
    ('{"username":"auth-student","password":"x"}', "text/plain"),
])
def test_login_rejects_malformed_body(user, csrf_client, payload, content_type):
    client, token = csrf_client
    response = client.post(
        "/api/auth/login/", data=payload, content_type=content_type,
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 400
    assert client.get("/api/auth/me/").status_code == 403


def test_login_rotates_prelogin_session_key_and_csrf_token(user):
    client = Client(enforce_csrf_checks=True)
    session = client.session
    session["anonymous_value"] = "test"
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    old_key = session.session_key
    old_csrf = client.get("/api/auth/csrf/").json()["csrfToken"]
    old_csrf_cookie = client.cookies[settings.CSRF_COOKIE_NAME].value

    assert post_login(client, old_csrf).status_code == 200
    assert client.cookies[settings.SESSION_COOKIE_NAME].value != old_key
    assert client.cookies[settings.CSRF_COOKIE_NAME].value != old_csrf_cookie
    assert client.get("/api/auth/me/").status_code == 200
    # A pre-login CSRF token is not valid after Django rotates the secret.
    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=old_csrf).status_code == 403
    current_csrf = client.get("/api/auth/csrf/").json()["csrfToken"]
    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=current_csrf).status_code == 204
    assert client.get("/api/auth/me/").status_code == 403


def test_logout_requires_csrf_without_invalidating_session(user, csrf_client):
    client, token = csrf_client
    assert post_login(client, token).status_code == 200
    assert client.post("/api/auth/logout/").status_code == 403
    assert client.get("/api/auth/me/").status_code == 200


def test_logout_clears_session_and_is_idempotent(user, csrf_client):
    client, token = csrf_client
    assert post_login(client, token).status_code == 200
    current_token = client.get("/api/auth/csrf/").json()["csrfToken"]
    session_key = client.cookies[settings.SESSION_COOKIE_NAME].value

    response = client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=current_token)
    assert response.status_code == 204
    assert not response.content
    assert not Session.objects.filter(session_key=session_key).exists()
    assert client.get("/api/auth/me/").status_code == 403
    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=current_token).status_code == 204


def test_anonymous_logout_is_idempotent_with_csrf(csrf_client):
    client, token = csrf_client
    for _ in range(2):
        response = client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == 204
        assert not response.content


def test_deactivated_user_can_still_logout(user, csrf_client):
    client, token = csrf_client
    assert post_login(client, token).status_code == 200
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    session_key = client.cookies[settings.SESSION_COOKIE_NAME].value
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert client.get("/api/auth/me/").status_code == 403

    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert not Session.objects.filter(session_key=session_key).exists()


def test_session_lifetime_and_server_side_expiry(user, csrf_client):
    client, token = csrf_client
    response = post_login(client, token)
    assert response.status_code == 200
    assert settings.SESSION_COOKIE_AGE == 1800
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.db"
    assert settings.SESSION_SAVE_EVERY_REQUEST is False

    session_cookie = response.cookies[settings.SESSION_COOKIE_NAME]
    assert int(session_cookie["max-age"]) == settings.SESSION_COOKIE_AGE
    assert bool(session_cookie["httponly"])
    assert session_cookie["samesite"] == "Lax"
    assert bool(session_cookie["secure"]) == settings.SESSION_COOKIE_SECURE

    key = client.cookies[settings.SESSION_COOKIE_NAME].value
    expiry_before = Session.objects.get(session_key=key).expire_date
    assert client.get("/api/auth/me/").status_code == 200
    assert Session.objects.get(session_key=key).expire_date == expiry_before

    Session.objects.filter(session_key=key).update(
        expire_date=timezone.now() - timedelta(seconds=1)
    )
    assert client.get("/api/auth/me/").status_code == 403


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=["testserver"],
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
)
def test_secure_cookie_flags_for_https_configuration(user):
    client = Client(enforce_csrf_checks=True)
    csrf_response = client.get("/api/auth/csrf/", secure=True)
    assert bool(csrf_response.cookies[settings.CSRF_COOKIE_NAME]["secure"])
    token = csrf_response.json()["csrfToken"]
    login_response = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": user.username, "password": VALID_PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_REFERER="https://testserver/api/auth/csrf/",
        secure=True,
    )
    assert login_response.status_code == 200
    assert bool(login_response.cookies[settings.SESSION_COOKIE_NAME]["secure"])
    assert bool(login_response.cookies[settings.CSRF_COOKIE_NAME]["secure"])


def test_https_environment_controls_secure_cookie_settings():
    env = dict(os.environ)
    env.update({
        "DJANGO_SECRET_KEY": "test-only-not-for-deployment-secret-key-stage13",
        "DJANGO_DEBUG": "False",
        "DJANGO_ALLOWED_HOSTS": "tests.example.invalid",
        "DJANGO_HTTPS": "True",
        "POSTGRES_DB": "unused",
        "POSTGRES_USER": "unused",
        "POSTGRES_PASSWORD": "unused",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "5432",
    })
    script = (
        "import config.settings as s; import json; "
        "print(json.dumps([s.DEBUG, s.ALLOWED_HOSTS, "
        "s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True, capture_output=True, text=True, env=env,
    )
    assert json.loads(result.stdout) == [False, ["tests.example.invalid"], True, True]
