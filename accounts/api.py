"""Session-based authentication endpoints (stage 13)."""

import json

from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


def _public_user(user):
    return {"id": user.pk, "username": user.username, "role": user.role}


@require_GET
@ensure_csrf_cookie
def csrf_view(request):
    """Issue a standard Django CSRF token without creating a login session."""
    return JsonResponse({"csrfToken": get_token(request)})


# Keep login as a Django view: DRF's SessionAuthentication does not enforce
# CSRF for anonymous requests, so login needs unconditional Django CSRF checks.
@csrf_protect
@require_POST
def login_view(request):
    if request.content_type != "application/json":
        return JsonResponse({"detail": "Invalid request body."}, status=400)

    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid request body."}, status=400)

    if (
        not isinstance(payload, dict)
        or set(payload) != {"username", "password"}
        or not isinstance(payload["username"], str)
        or not isinstance(payload["password"], str)
        or not payload["username"]
        or not payload["password"]
    ):
        return JsonResponse({"detail": "Invalid request body."}, status=400)

    user = authenticate(
        request,
        username=payload["username"],
        password=payload["password"],
    )
    if user is None or not user.is_active:
        # Do not reveal whether the username exists or the account is blocked.
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    login(request, user)  # Server-side session + session-key/CSRF rotation.
    return JsonResponse(_public_user(user))


# Logout must still work for anonymous or newly deactivated users. Keeping it
# outside DRF's active-session authentication avoids rejecting those requests.
@csrf_protect
@require_POST
def logout_view(request):
    logout(request)
    return HttpResponse(status=204)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def me_view(request):
    if not request.user.is_active:
        return Response(
            {"detail": "Authentication credentials were not provided."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return Response(_public_user(request.user))
