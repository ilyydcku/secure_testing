from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Barrier, Event

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections, transaction

from accounts.models import User
from accounts.services import (
    UsernameConflictError,
    change_user_role,
    create_user,
)


# Real commits, row locks and separate connections are required for these tests.
pytestmark = pytest.mark.django_db(transaction=True)

VALID_PASSWORD = "F9!vQ2#sLm7@pX4z"


def test_concurrent_bootstrap_creates_exactly_one_admin(monkeypatch):
    # Both commands must pass their initial exists() check before either
    # proceeds, so this test reproduces the original TOCTOU window.
    both_at_password_prompt = Barrier(2, timeout=15)

    def concurrent_password_input(prompt):
        if prompt == "Password: ":
            both_at_password_prompt.wait()
        return VALID_PASSWORD

    monkeypatch.setattr(
        "accounts.management.commands.bootstrap_admin.getpass",
        concurrent_password_input,
    )

    def bootstrap(username):
        close_old_connections()
        try:
            try:
                call_command("bootstrap_admin", username=username)
                return "created"
            except CommandError as exc:
                if "already exists" in str(exc):
                    return "already_exists"
                raise
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(bootstrap, "concurrent-bootstrap-1")
        second = pool.submit(bootstrap, "concurrent-bootstrap-2")
        outcomes = [first.result(timeout=40), second.result(timeout=40)]

    assert sorted(outcomes) == ["already_exists", "created"]
    admins = User.objects.filter(role="ADMIN")
    assert admins.count() == 1
    assert admins.get().is_active is True


def test_concurrent_duplicate_username_returns_domain_conflict(monkeypatch):
    both_at_save = Barrier(2, timeout=15)
    original_save = User.save

    def synchronized_save(self, *args, **kwargs):
        both_at_save.wait()
        return original_save(self, *args, **kwargs)

    # Both transactions pass the preliminary exists() check; the DB UNIQUE
    # constraint must arbitrate the actual simultaneous INSERT operations.
    monkeypatch.setattr(User, "save", synchronized_save)

    def create_same_username():
        close_old_connections()
        try:
            try:
                create_user(
                    username="concurrent-duplicate",
                    password=VALID_PASSWORD,
                    role="STUDENT",
                )
                return "created"
            except UsernameConflictError:
                return "username_conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(create_same_username)
        second = pool.submit(create_same_username)
        outcomes = [first.result(timeout=40), second.result(timeout=40)]

    assert sorted(outcomes) == ["created", "username_conflict"]
    assert User.objects.filter(username="concurrent-duplicate").count() == 1


def test_role_change_waits_for_user_row_lock():
    admin = create_user(
        username="row-lock-admin",
        password=VALID_PASSWORD,
        role="ADMIN",
    )
    teacher = create_user(
        username="row-lock-teacher",
        password=VALID_PASSWORD,
        role="TEACHER",
    )

    lock_acquired = Event()
    release_lock = Event()
    change_started = Event()
    sql_statements = []

    def hold_user_row_lock():
        close_old_connections()
        try:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=teacher.pk)
                lock_acquired.set()
                if not release_lock.wait(timeout=15):
                    raise TimeoutError("Timed out waiting to release row lock")
        finally:
            connections.close_all()

    def change_role_with_sql_capture():
        close_old_connections()

        def capture_sql(execute, sql, params, many, context):
            sql_statements.append(sql)
            return execute(sql, params, many, context)

        try:
            change_started.set()
            with connection.execute_wrapper(capture_sql):
                change_user_role(
                    target_user_id=teacher.pk,
                    new_role="STUDENT",
                    acting_user_id=admin.pk,
                )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(hold_user_row_lock)
        try:
            assert lock_acquired.wait(timeout=10)
            changer = pool.submit(change_role_with_sql_capture)
            assert change_started.wait(timeout=10)
            with pytest.raises(FutureTimeoutError):
                changer.result(timeout=0.3)
        finally:
            release_lock.set()

        holder.result(timeout=20)
        changer.result(timeout=20)

    assert any("FOR UPDATE" in sql.upper() for sql in sql_statements)
    teacher.refresh_from_db()
    assert teacher.role == "STUDENT"
