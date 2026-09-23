"""Run on PostgreSQL: real row locks and separate committed transactions."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Barrier, Event

import pytest
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections, transaction

from accounts.models import User
from accounts.services import ActiveTeacherRoleChangeError, change_user_role
from assessments import services
from assessments.access import LifecycleConflict
from assessments.models import AnswerOption, Question, Test as Assessment, TestAssignment as Assignment

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def rows():
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks; SQLite is not concurrency evidence.')
    teacher = User.objects.create_user(username='teacher', role='TEACHER')
    student = User.objects.create_user(username='student', role='STUDENT')
    test = Assessment.objects.create(owner=teacher, title='Locked')
    q = Question.objects.create(test=test, text='Question', position=1)
    option = AnswerOption.objects.create(question=q, text='Yes', position=1, is_correct=True)
    AnswerOption.objects.create(question=q, text='No', position=2)
    return teacher, student, test, q, option


def worker(operation, started, table):
    close_old_connections()
    def capture(execute, sql, params, many, context):
        if 'FOR UPDATE' in sql.upper() and table in sql:
            started.set()
        return execute(sql, params, many, context)
    try:
        with connection.execute_wrapper(capture):
            return operation()
    finally:
        connections.close_all()


@pytest.mark.parametrize('kind', ['test', 'question-create', 'question-update', 'option-create', 'option-update', 'editor', 'assignment'])
def test_waiting_write_rechecks_lifecycle(rows, kind):
    teacher, student, test, question, option = rows
    operations = {
        'test': lambda: services.update_test(teacher, test.pk, {'title': 'Forbidden'}),
        'question-create': lambda: services.create_question(teacher, test.pk, {'text': 'Forbidden', 'position': 2}),
        'question-update': lambda: services.update_question(teacher, question.pk, {'text': 'Forbidden'}),
        'option-create': lambda: services.create_option(teacher, question.pk, {'text': 'Forbidden', 'position': 3}),
        'option-update': lambda: services.update_option(teacher, option.pk, {'text': 'Forbidden'}),
        'editor': lambda: services.save_question_editor(teacher, test.pk, question.pk, {'text': 'Forbidden', 'position': 1}, []),
        'assignment': lambda: services.create_assignment(teacher, test.pk, {'student_id': student.pk}),
    }
    started = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Assessment.objects.select_for_update().get(pk=test.pk)
            future = pool.submit(worker, operations[kind], started, 'assessments_test')
            assert started.wait(10)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=.2)
            Assessment.objects.filter(pk=test.pk).update(status='CLOSED' if kind == 'assignment' else 'ACTIVE')
        with pytest.raises(LifecycleConflict):
            future.result(timeout=10)
    assert not Question.objects.filter(text='Forbidden').exists()
    assert not AnswerOption.objects.filter(text='Forbidden').exists()
    assert not Assignment.objects.exists()
    test.refresh_from_db()
    assert test.title == 'Locked'


def test_activation_waits_for_owner_and_rechecks_role(rows):
    teacher, _, test, _, _ = rows
    started = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=teacher.pk)
            future = pool.submit(worker, lambda: services.activate_test(teacher, test.pk, {}), started, 'accounts_user')
            assert started.wait(10)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=.2)
            User.objects.filter(pk=teacher.pk).update(role='STUDENT')
        with pytest.raises(PermissionDenied):
            future.result(timeout=10)
    test.refresh_from_db()
    assert test.status == 'DRAFT'


def test_role_change_waits_for_activation_then_conflicts(rows):
    teacher, student, test, _, _ = rows
    started = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            services.activate_test(teacher, test.pk, {})
            future = pool.submit(worker, lambda: change_user_role(target_user_id=teacher.pk, new_role='STUDENT', acting_user_id=student.pk), started, 'accounts_user')
            assert started.wait(10)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=.2)
        with pytest.raises(ActiveTeacherRoleChangeError):
            future.result(timeout=10)
    teacher.refresh_from_db()
    assert teacher.role == 'TEACHER'


def test_concurrent_assignment_has_one_winner(rows):
    teacher, student, test, _, _ = rows
    barrier = Barrier(2, timeout=10)
    def assign():
        close_old_connections()
        try:
            barrier.wait()
            try:
                services.create_assignment(teacher, test.pk, {'student_id': student.pk})
                return 'created'
            except LifecycleConflict:
                return 'conflict'
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(assign) for _ in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == ['conflict', 'created']
    assert Assignment.objects.filter(test=test, student=student).count() == 1


def test_assignment_waits_for_student_and_rechecks_eligibility(rows):
    teacher, student, test, _, _ = rows
    started = Event()
    from rest_framework.exceptions import ValidationError
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=student.pk)
            future = pool.submit(worker, lambda: services.create_assignment(teacher, test.pk, {'student_id': student.pk}), started, 'accounts_user')
            assert started.wait(10)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=.2)
            User.objects.filter(pk=student.pk).update(is_active=False)
        with pytest.raises(ValidationError):
            future.result(timeout=10)
    assert not Assignment.objects.exists()
