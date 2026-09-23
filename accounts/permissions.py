"""Business-role checks shared by DRF and Django views (stage 14)."""

from functools import wraps

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from accounts.services import ALLOWED_ROLES


def has_role(user, role):
    """Check the current request user; technical Django flags grant no access."""
    return bool(
        role in ALLOWED_ROLES
        and user.is_authenticated
        and user.is_active
        and user.role == role
    )


def check_role(user, role):
    """Require a business role before querying any protected objects."""
    if not has_role(user, role):
        raise PermissionDenied


class HasBusinessRole(BasePermission):
    required_role = None

    def has_permission(self, request, view):
        return has_role(request.user, self.required_role)


class IsStudent(HasBusinessRole):
    required_role = "STUDENT"


class IsTeacher(HasBusinessRole):
    required_role = "TEACHER"


class IsAdmin(HasBusinessRole):
    required_role = "ADMIN"


def require_role(role):
    """Protect a Django view without redirects or alternative authentication."""
    if role not in ALLOWED_ROLES:
        raise ValueError("Unknown business role.")

    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not has_role(request.user, role):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorate
