from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from assessments.models import Test


ALLOWED_ROLES = frozenset({"STUDENT", "TEACHER", "ADMIN"})


class UserServiceError(Exception):
    pass


class UserDomainConflict(UserServiceError):
    pass


class UsernameConflictError(UserDomainConflict):
    pass


class ActiveTeacherRoleChangeError(UserDomainConflict):
    pass


class SelfRoleChangeError(UserDomainConflict):
    pass


class SelfDeactivationError(UserDomainConflict):
    pass


def _validate_role(role):
    if role not in ALLOWED_ROLES:
        raise ValidationError(
            {"role": ["Role must be STUDENT, TEACHER or ADMIN."]}
        )


def _is_username_unique_violation(exc, User):
    # PostgreSQL names the UNIQUE constraint for the AbstractUser username
    # column <table>_username_key; do not mask unrelated IntegrityError cases.
    cause = exc.__cause__
    return (
        getattr(cause, "sqlstate", None) == "23505"
        and getattr(getattr(cause, "diag", None), "constraint_name", None)
        == f"{User._meta.db_table}_username_key"
    )


@transaction.atomic
def create_user(*, username, password, role):
    _validate_role(role)

    User = get_user_model()
    user = User(
        username=username,
        role=role,
        is_active=True,
    )

    user.full_clean(exclude=["password"], validate_unique=False)

    if User.objects.filter(username=user.username).exists():
        raise UsernameConflictError("A user with this username already exists.")

    if not isinstance(password, str) or not password:
        raise ValidationError({"password": ["A non-empty password is required."]})

    validate_password(password, user=user)
    user.set_password(password)

    try:
        user.save()
    except IntegrityError as exc:
        if _is_username_unique_violation(exc, User):
            raise UsernameConflictError(
                "A user with this username already exists."
            ) from exc
        raise

    return user


@transaction.atomic
def change_user_role(*, target_user_id, new_role, acting_user_id):
    _validate_role(new_role)

    User = get_user_model()
    target_user = User.objects.select_for_update().get(pk=target_user_id)

    if target_user.pk == acting_user_id:
        raise SelfRoleChangeError(
            "An administrator cannot change their own business role."
        )

    if target_user.role == new_role:
        return target_user

    if (
        target_user.role == "TEACHER"
        and new_role != "TEACHER"
        and Test.objects.filter(
            owner_id=target_user.pk,
            status="ACTIVE",
        ).exists()
    ):
        raise ActiveTeacherRoleChangeError(
            "A TEACHER with an ACTIVE test cannot change business role."
        )

    target_user.role = new_role
    target_user.save(update_fields=["role"])
    return target_user


@transaction.atomic
def set_user_active(*, target_user_id, is_active, acting_user_id):
    if not isinstance(is_active, bool):
        raise ValidationError(
            {"is_active": ["is_active must be a boolean value."]}
        )

    User = get_user_model()
    target_user = User.objects.select_for_update().get(pk=target_user_id)

    if target_user.pk == acting_user_id and not is_active:
        raise SelfDeactivationError(
            "An administrator cannot deactivate their own account."
        )

    if target_user.is_active == is_active:
        return target_user

    target_user.is_active = is_active
    target_user.save(update_fields=["is_active"])
    return target_user
