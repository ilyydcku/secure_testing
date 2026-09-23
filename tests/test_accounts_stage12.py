import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError

from accounts.models import User
from accounts.services import (
    ActiveTeacherRoleChangeError,
    SelfDeactivationError,
    SelfRoleChangeError,
    UsernameConflictError,
    change_user_role,
    create_user,
    set_user_active,
)
from assessments.models import Test as AssessmentTest


pytestmark = pytest.mark.django_db

VALID_PASSWORD = "F9!vQ2#sLm7@pX4z"


def test_create_user_hashes_password_and_sets_expected_fields():
    user = create_user(
        username="student1",
        password=VALID_PASSWORD,
        role="STUDENT",
    )

    assert user.username == "student1"
    assert user.role == "STUDENT"
    assert user.is_active is True
    assert user.check_password(VALID_PASSWORD)
    assert user.password != VALID_PASSWORD
    assert user.password.startswith("pbkdf2_sha256$")


def test_create_user_rejects_invalid_role():
    with pytest.raises(ValidationError):
        create_user(
            username="invalid-role-user",
            password=VALID_PASSWORD,
            role="UNKNOWN",
        )


def test_create_user_uses_django_password_validators():
    with pytest.raises(ValidationError):
        create_user(
            username="weak-password-user",
            password="123",
            role="STUDENT",
        )


def test_create_user_rejects_duplicate_username():
    create_user(
        username="duplicate-user",
        password=VALID_PASSWORD,
        role="STUDENT",
    )

    with pytest.raises(UsernameConflictError):
        create_user(
            username="duplicate-user",
            password=VALID_PASSWORD,
            role="TEACHER",
        )


def test_teacher_with_active_test_cannot_change_role():
    admin = create_user(
        username="admin-active-test",
        password=VALID_PASSWORD,
        role="ADMIN",
    )
    teacher = create_user(
        username="teacher-active-test",
        password=VALID_PASSWORD,
        role="TEACHER",
    )
    AssessmentTest.objects.create(
        owner=teacher,
        title="Active test",
        status="ACTIVE",
        max_attempts=1,
    )

    with pytest.raises(ActiveTeacherRoleChangeError):
        change_user_role(
            target_user_id=teacher.pk,
            new_role="STUDENT",
            acting_user_id=admin.pk,
        )

    teacher.refresh_from_db()
    assert teacher.role == "TEACHER"


@pytest.mark.parametrize("test_status", ["DRAFT", "CLOSED"])
def test_teacher_without_active_test_can_change_role(test_status):
    admin = create_user(
        username=f"admin-{test_status.lower()}",
        password=VALID_PASSWORD,
        role="ADMIN",
    )
    teacher = create_user(
        username=f"teacher-{test_status.lower()}",
        password=VALID_PASSWORD,
        role="TEACHER",
    )
    AssessmentTest.objects.create(
        owner=teacher,
        title=f"{test_status} test",
        status=test_status,
        max_attempts=1,
    )

    change_user_role(
        target_user_id=teacher.pk,
        new_role="STUDENT",
        acting_user_id=admin.pk,
    )

    teacher.refresh_from_db()
    assert teacher.role == "STUDENT"


def test_admin_cannot_change_own_role():
    admin = create_user(
        username="self-role-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )

    with pytest.raises(SelfRoleChangeError):
        change_user_role(
            target_user_id=admin.pk,
            new_role="STUDENT",
            acting_user_id=admin.pk,
        )

    admin.refresh_from_db()
    assert admin.role == "ADMIN"


def test_admin_cannot_deactivate_own_account():
    admin = create_user(
        username="self-deactivate-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )

    with pytest.raises(SelfDeactivationError):
        set_user_active(
            target_user_id=admin.pk,
            is_active=False,
            acting_user_id=admin.pk,
        )

    admin.refresh_from_db()
    assert admin.is_active is True


def test_admin_can_deactivate_and_reactivate_other_user():
    admin = create_user(
        username="active-state-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )
    student = create_user(
        username="active-state-student",
        password=VALID_PASSWORD,
        role="STUDENT",
    )

    set_user_active(
        target_user_id=student.pk,
        is_active=False,
        acting_user_id=admin.pk,
    )
    student.refresh_from_db()
    assert student.is_active is False

    set_user_active(
        target_user_id=student.pk,
        is_active=True,
        acting_user_id=admin.pk,
    )
    student.refresh_from_db()
    assert student.is_active is True


def test_set_user_active_rejects_non_boolean_value():
    admin = create_user(
        username="boolean-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )
    student = create_user(
        username="boolean-student",
        password=VALID_PASSWORD,
        role="STUDENT",
    )

    with pytest.raises(ValidationError):
        set_user_active(
            target_user_id=student.pk,
            is_active="false",
            acting_user_id=admin.pk,
        )


def test_bootstrap_admin_creates_first_business_admin(monkeypatch):
    passwords = iter([VALID_PASSWORD, VALID_PASSWORD])
    monkeypatch.setattr(
        "accounts.management.commands.bootstrap_admin.getpass",
        lambda _prompt: next(passwords),
    )

    call_command("bootstrap_admin", username="bootstrap-admin")

    admin = User.objects.get(username="bootstrap-admin")
    assert admin.role == "ADMIN"
    assert admin.is_active is True
    assert admin.is_staff is False
    assert admin.is_superuser is False
    assert admin.check_password(VALID_PASSWORD)


def test_bootstrap_admin_refuses_second_business_admin(monkeypatch):
    create_user(
        username="existing-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )

    with pytest.raises(CommandError, match="already exists"):
        call_command("bootstrap_admin", username="second-admin")


def test_bootstrap_admin_rejects_password_mismatch(monkeypatch):
    passwords = iter([VALID_PASSWORD, "Different9!Password"])
    monkeypatch.setattr(
        "accounts.management.commands.bootstrap_admin.getpass",
        lambda _prompt: next(passwords),
    )

    with pytest.raises(CommandError, match="do not match"):
        call_command("bootstrap_admin", username="mismatch-admin")

    assert not User.objects.filter(username="mismatch-admin").exists()


@pytest.mark.parametrize("username", ["", "bad username", "x" * 151])
def test_create_user_rejects_invalid_username_without_saving(username):
    with pytest.raises(ValidationError):
        create_user(
            username=username,
            password=VALID_PASSWORD,
            role="STUDENT",
        )

    assert not User.objects.filter(username=username).exists()


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("short-pw-user", "Az7!"),
        ("numeric-pw-user", "829173864520"),
        ("common-pw-user", "password"),
        ("thisismyveryuniquename", "thisismyveryuniquename"),
    ],
)
def test_each_standard_password_validator_rejects_invalid_password(
    username, password
):
    with pytest.raises(ValidationError):
        create_user(
            username=username,
            password=password,
            role="STUDENT",
        )

    assert not User.objects.filter(username=username).exists()


@pytest.mark.parametrize("password", [None, ""])
def test_create_user_requires_nonempty_password(password):
    with pytest.raises(ValidationError):
        create_user(
            username="missing-password-user",
            password=password,
            role="STUDENT",
        )

    assert not User.objects.filter(username="missing-password-user").exists()


def test_non_username_integrity_error_is_not_masked(monkeypatch):
    def unrelated_integrity_error(_user):
        raise IntegrityError("A different database constraint failed.")

    monkeypatch.setattr(User, "save", unrelated_integrity_error)

    with pytest.raises(
        IntegrityError, match="A different database constraint failed"
    ):
        create_user(
            username="unrelated-integrity-user",
            password=VALID_PASSWORD,
            role="STUDENT",
        )


def test_teacher_with_mixed_test_statuses_cannot_change_role():
    admin = create_user(
        username="mixed-tests-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )
    teacher = create_user(
        username="mixed-tests-teacher",
        password=VALID_PASSWORD,
        role="TEACHER",
    )
    for status in ("DRAFT", "ACTIVE", "CLOSED"):
        AssessmentTest.objects.create(
            owner=teacher, title=status, status=status, max_attempts=1,
        )

    with pytest.raises(ActiveTeacherRoleChangeError):
        change_user_role(
            target_user_id=teacher.pk,
            new_role="STUDENT",
            acting_user_id=admin.pk,
        )

    teacher.refresh_from_db()
    assert teacher.role == "TEACHER"


def test_role_change_to_same_role_is_idempotent():
    admin = create_user(
        username="same-role-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )
    teacher = create_user(
        username="same-role-teacher",
        password=VALID_PASSWORD,
        role="TEACHER",
    )
    AssessmentTest.objects.create(
        owner=teacher,
        title="Active",
        status="ACTIVE",
        max_attempts=1,
    )

    updated = change_user_role(
        target_user_id=teacher.pk,
        new_role="TEACHER",
        acting_user_id=admin.pk,
    )
    assert updated.role == "TEACHER"


def test_set_user_active_is_idempotent():
    admin = create_user(
        username="idempotent-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )
    student = create_user(
        username="idempotent-student",
        password=VALID_PASSWORD,
        role="STUDENT",
    )

    set_user_active(
        target_user_id=student.pk,
        is_active=True,
        acting_user_id=admin.pk,
    )
    set_user_active(
        target_user_id=student.pk,
        is_active=False,
        acting_user_id=admin.pk,
    )
    set_user_active(
        target_user_id=student.pk,
        is_active=False,
        acting_user_id=admin.pk,
    )
    student.refresh_from_db()
    assert student.is_active is False


def test_bootstrap_admin_rejects_weak_password(monkeypatch):
    monkeypatch.setattr(
        "accounts.management.commands.bootstrap_admin.getpass",
        lambda _prompt: "123",
    )

    with pytest.raises(CommandError):
        call_command("bootstrap_admin", username="weak-bootstrap-admin")

    assert not User.objects.filter(role="ADMIN").exists()


def test_bootstrap_admin_rejects_invalid_username(monkeypatch):
    monkeypatch.setattr(
        "accounts.management.commands.bootstrap_admin.getpass",
        lambda _prompt: VALID_PASSWORD,
    )

    with pytest.raises(CommandError):
        call_command("bootstrap_admin", username="invalid bootstrap username")

    assert not User.objects.filter(role="ADMIN").exists()
