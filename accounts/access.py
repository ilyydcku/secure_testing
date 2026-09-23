"""User access scopes. Returned model objects are internal, not API payloads."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import Http404

from accounts.permissions import check_role


def admin_users(user):
    check_role(user, "ADMIN")
    return get_user_model().objects.all()


def admin_user(user, user_id):
    try:
        return admin_users(user).get(pk=user_id)
    except get_user_model().DoesNotExist:
        raise Http404("Not found.") from None


def assignable_students(user):
    check_role(user, "TEACHER")
    return get_user_model().objects.filter(
        role="STUDENT", is_active=True,
    ).values("id", "username")


def assignment_student(user, student_id):
    # Missing, inactive and non-STUDENT targets have the same neutral error.
    try:
        return assignable_students(user).get(pk=student_id)
    except (get_user_model().DoesNotExist, ValueError, TypeError):
        raise ValidationError("Invalid related object.") from None
