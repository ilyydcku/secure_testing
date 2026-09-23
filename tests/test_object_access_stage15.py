"""Object scopes and IDOR checks, including real session requests to test routes."""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.test import Client
from django.urls import path
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts import access as users
from assessments import access
from assessments.models import (
    AnswerOption, Attempt, Question, Result, StudentAnswer, Test as Assessment,
    TestAssignment as Assignment,
)
from auditlog.access import admin_events
from auditlog.models import AuditEvent


pytestmark = pytest.mark.django_db


@pytest.fixture
def graph():
    User = get_user_model()
    people = {}
    for name, role in (
        ("teacher", "TEACHER"), ("other_teacher", "TEACHER"),
        ("student", "STUDENT"), ("other_student", "STUDENT"), ("admin", "ADMIN"),
    ):
        people[name] = User.objects.create(username=name, role=role, password="!")
    g = SimpleNamespace(**people)
    for name, owner, state in (
        ("test", g.teacher, "ACTIVE"), ("foreign_test", g.other_teacher, "ACTIVE"),
        ("draft", g.teacher, "DRAFT"), ("closed", g.teacher, "CLOSED"),
    ):
        setattr(g, name, Assessment.objects.create(
            owner=owner, title=name, status=state, max_attempts=3,
        ))
    for name, test, student in (
        ("assignment", g.test, g.student),
        ("other_assignment", g.test, g.other_student),
        ("foreign_assignment", g.foreign_test, g.other_student),
        ("draft_assignment", g.draft, g.student),
        ("closed_assignment", g.closed, g.student),
    ):
        setattr(g, name, Assignment.objects.create(test=test, student=student))
    now = timezone.now()
    for name, assignment, completed in (
        ("attempt", g.assignment, False), ("other_attempt", g.other_assignment, False),
        ("foreign_attempt", g.foreign_assignment, False),
        ("done", g.assignment, True), ("foreign_done", g.foreign_assignment, True),
        ("other_done", g.other_assignment, True), ("closed_attempt", g.closed_assignment, False),
    ):
        setattr(g, name, Attempt.objects.create(
            assignment=assignment, started_at=now, completed_at=now if completed else None,
        ))
    for name, test, position in (
        ("question", g.test, 1), ("question2", g.test, 2),
        ("foreign_question", g.foreign_test, 1), ("closed_question", g.closed, 1),
    ):
        setattr(g, name, Question.objects.create(test=test, text=name, position=position))
    for name, question in (
        ("option", g.question), ("option2", g.question2),
        ("foreign_option", g.foreign_question), ("closed_option", g.closed_question),
    ):
        setattr(g, name, AnswerOption.objects.create(
            question=question, text=name, position=1, is_correct=True,
        ))
    for name, attempt, question, option in (
        ("answer", g.attempt, g.question, g.option),
        ("other_answer", g.other_attempt, g.question, g.option),
        ("foreign_answer", g.foreign_attempt, g.foreign_question, g.foreign_option),
    ):
        setattr(g, name, StudentAnswer.objects.create(
            attempt=attempt, question=question, answer_option=option,
        ))
    for name, attempt in (
        ("result", g.done), ("other_result", g.other_done), ("foreign_result", g.foreign_done),
    ):
        setattr(g, name, Result.objects.create(
            attempt=attempt, score_points=1, correct_percentage="100.00",
        ))
    g.event = AuditEvent.objects.create(
        occurred_at=now, category="security", event_type="test", actor=g.student,
    )
    return g


# Each public entry point must perform RBAC, including list queries.
CASES = [
    (users.admin_users, "ADMIN", ()),
    (users.admin_user, "ADMIN", ("student",)),
    (users.assignable_students, "TEACHER", ()),
    (users.assignment_student, "TEACHER", ("student",)),
    (admin_events, "ADMIN", ()),
    (access.teacher_tests, "TEACHER", ()),
    (access.teacher_test, "TEACHER", ("test",)),
    (access.teacher_questions, "TEACHER", ("test",)),
    (access.teacher_question, "TEACHER", ("question",)),
    (access.teacher_answer_options, "TEACHER", ("question",)),
    (access.teacher_answer_option, "TEACHER", ("option",)),
    (access.teacher_assignments, "TEACHER", ("test",)),
    (access.teacher_assignment, "TEACHER", ("assignment",)),
    (access.teacher_results, "TEACHER", ("test",)),
    (access.teacher_result, "TEACHER", ("result",)),
    (access.student_tests, "STUDENT", ()),
    (access.student_test, "STUDENT", ("test",)),
    (access.student_attempts, "STUDENT", ("test",)),
    (access.student_attempt, "STUDENT", ("attempt",)),
    (access.student_in_progress_attempt, "STUDENT", ("attempt",)),
    (access.student_questions, "STUDENT", ("attempt",)),
    (access.student_answers, "STUDENT", ("attempt",)),
    (access.student_answer_selection, "STUDENT", ("attempt", "question", "option")),
    (access.student_result, "STUDENT", ("done",)),
]


@pytest.mark.parametrize("function,required,arguments", CASES, ids=[c[0].__name__ for c in CASES])
@pytest.mark.parametrize("role", ["STUDENT", "TEACHER", "ADMIN"])
def test_each_scope_checks_current_role(graph, function, required, arguments, role):
    actor = getattr(graph, role.lower())
    # Technical privileges must not change the result.
    actor.is_staff = actor.is_superuser = True
    args = [getattr(graph, name).pk for name in arguments]
    if role == required:
        assert function(actor, *args) is not None
    else:
        with pytest.raises(PermissionDenied):
            function(actor, *args)


@pytest.mark.parametrize("function,required,arguments", CASES, ids=[c[0].__name__ for c in CASES])
@pytest.mark.parametrize("anonymous", [True, False])
def test_denial_precedes_all_object_queries(graph, django_assert_num_queries,
                                          function, required, arguments, anonymous):
    actor = AnonymousUser() if anonymous else getattr(graph, required.lower())
    if not anonymous:
        actor.is_active = False
    with django_assert_num_queries(0), pytest.raises(PermissionDenied):
        function(actor, *[getattr(graph, name).pk for name in arguments])


TEACHER_OBJECTS = [
    (access.teacher_test, "test", "foreign_test"),
    (access.teacher_question, "question", "foreign_question"),
    (access.teacher_answer_option, "option", "foreign_option"),
    (access.teacher_assignment, "assignment", "foreign_assignment"),
    (access.teacher_result, "result", "foreign_result"),
]


@pytest.mark.parametrize("function,own,foreign", TEACHER_OBJECTS)
def test_teacher_object_chains_and_neutral_not_found(graph, function, own, foreign):
    assert function(graph.teacher, getattr(graph, own).pk) == getattr(graph, own)
    messages = []
    for pk in (getattr(graph, foreign).pk, 999999):
        with pytest.raises(Http404) as exc:
            function(graph.teacher, pk)
        messages.append(str(exc.value))
    assert messages == ["Not found.", "Not found."]


def test_lists_filter_both_owner_and_nested_parent(graph):
    g = graph
    assert set(access.teacher_tests(g.teacher)) == {g.test, g.draft, g.closed}
    assert list(access.teacher_questions(g.teacher, g.test.pk)) == [g.question, g.question2]
    assert list(access.teacher_answer_options(g.teacher, g.question.pk)) == [g.option]
    assert set(access.teacher_assignments(g.teacher, g.test.pk)) == {g.assignment, g.other_assignment}
    assert set(access.teacher_results(g.teacher, g.test.pk)) == {g.result, g.other_result}
    assert set(access.student_tests(g.student)) == {g.test, g.closed}
    assert set(access.student_attempts(g.student, g.test.pk)) == {g.attempt, g.done}
    assert list(access.student_answers(g.student, g.attempt.pk)) == [g.answer]
    assert access.student_result(g.student, g.done.pk) == g.result


@pytest.mark.parametrize("function,parent", [
    (access.teacher_questions, "foreign_test"),
    (access.teacher_answer_options, "foreign_question"),
    (access.teacher_assignments, "foreign_test"),
    (access.teacher_results, "foreign_test"),
    (access.student_attempts, "foreign_test"),
])
def test_nested_list_denies_foreign_or_missing_parent(graph, function, parent):
    actor = graph.student if function == access.student_attempts else graph.teacher
    for pk in (getattr(graph, parent).pk, 999999):
        with pytest.raises(Http404, match="Not found"):
            function(actor, pk)


@pytest.mark.parametrize("target", ["draft", "foreign_test"])
def test_student_cannot_access_draft_or_unassigned_test(graph, target):
    for function in (access.student_test, access.student_attempts):
        with pytest.raises(Http404):
            function(graph.student, getattr(graph, target).pk)


@pytest.mark.parametrize("function", [
    access.student_attempt, access.student_questions, access.student_answers, access.student_result,
])
@pytest.mark.parametrize("target", ["other_attempt", "foreign_attempt", "foreign_done", "missing"])
def test_student_attempt_scope_precedes_lifecycle(graph, function, target):
    pk = 999999 if target == "missing" else getattr(graph, target).pk
    with pytest.raises(Http404, match="Not found"):
        function(graph.student, pk)


def test_no_questions_before_start_and_no_content_after_completion(graph):
    with pytest.raises(Http404):
        access.student_questions(graph.student, 999999)
    for function in (access.student_questions, access.student_answers):
        with pytest.raises(access.LifecycleConflict):
            function(graph.student, graph.done.pk)
    with pytest.raises(access.LifecycleConflict):
        access.student_result(graph.student, graph.attempt.pk)
    with pytest.raises(access.LifecycleConflict):
        access.student_answer_selection(graph.student, graph.done.pk, graph.question.pk, graph.option.pk)


def test_closed_test_preserves_started_attempt_and_selection(graph):
    g = graph
    assert list(access.student_questions(g.student, g.closed_attempt.pk)) == [g.closed_question]
    assert access.student_answer_selection(
        g.student, g.closed_attempt.pk, g.closed_question.pk, g.closed_option.pk,
    ) == (g.closed_attempt, g.closed_question, g.closed_option)
    g.test.status = "CLOSED"
    g.test.save(update_fields=["status"])
    assert access.student_attempt(g.student, g.attempt.pk) == g.attempt
    assert list(access.student_questions(g.student, g.attempt.pk)) == [g.question, g.question2]


def test_inconsistent_draft_attempt_cannot_expose_content(graph):
    attempt = Attempt.objects.create(
        assignment=graph.draft_assignment, started_at=timezone.now(),
    )
    with pytest.raises(Http404):
        access.student_questions(graph.student, attempt.pk)


@pytest.mark.parametrize("question,option", [
    ("foreign_question", "foreign_option"), ("question", "foreign_option"),
    ("question", "option2"), ("missing", "option"), ("question", "missing"),
])
def test_substituted_links_return_same_neutral_error_without_writes(graph, question, option):
    qid = 999999 if question == "missing" else getattr(graph, question).pk
    oid = 999999 if option == "missing" else getattr(graph, option).pk
    before = list(StudentAnswer.objects.values())
    with pytest.raises(ValidationError) as exc:
        access.student_answer_selection(graph.student, graph.attempt.pk, qid, oid)
    assert exc.value.messages == ["Invalid related object."]
    assert list(StudentAnswer.objects.values()) == before


def test_selection_checks_attempt_before_supplied_links(graph):
    with pytest.raises(Http404):
        access.student_answer_selection(graph.student, graph.other_attempt.pk, 999999, 999999)
    assert access.student_answer_selection(
        graph.student, graph.attempt.pk, graph.question.pk, graph.option.pk,
    ) == (graph.attempt, graph.question, graph.option)


@pytest.mark.parametrize("broken_link", ["question", "option"])
def test_corrupt_student_answer_links_are_not_exposed(graph, broken_link):
    if broken_link == "question":
        StudentAnswer.objects.filter(pk=graph.answer.pk).update(
            question=graph.foreign_question, answer_option=graph.foreign_option,
        )
    else:
        StudentAnswer.objects.filter(pk=graph.answer.pk).update(answer_option=graph.option2)
    assert not access.student_answers(graph.student, graph.attempt.pk).exists()


def test_assignment_student_list_has_only_allowed_fields_and_current_candidates(graph):
    graph.other_student.is_active = False
    graph.other_student.save(update_fields=["is_active"])
    expected = {"id": graph.student.pk, "username": graph.student.username}
    assert list(users.assignable_students(graph.teacher)) == [expected]
    assert users.assignment_student(graph.teacher, graph.student.pk) == expected
    for pk in (graph.other_student.pk, graph.teacher.pk, graph.admin.pk, 999999):
        with pytest.raises(ValidationError) as exc:
            users.assignment_student(graph.teacher, pk)
        assert exc.value.messages == ["Invalid related object."]


def test_admin_scopes(graph):
    assert users.admin_user(graph.admin, graph.student.pk) == graph.student
    assert users.admin_users(graph.admin).count() == 5
    assert list(admin_events(graph.admin)) == [graph.event]
    with pytest.raises(Http404, match="Not found"):
        users.admin_user(graph.admin, 999999)


def test_former_teacher_does_not_invalidate_student_historical_access(graph):
    graph.test.status = "CLOSED"
    graph.test.save(update_fields=["status"])
    graph.closed.owner.role = "ADMIN"
    graph.closed.owner.save(update_fields=["role"])
    assert access.student_test(graph.student, graph.closed.pk) == graph.closed
    assert access.student_attempt(graph.student, graph.closed_attempt.pk) == graph.closed_attempt


def test_historical_links_do_not_preserve_old_role_permissions(graph):
    graph.test.status = "CLOSED"
    graph.test.save(update_fields=["status"])
    graph.teacher.role = "STUDENT"
    graph.teacher.save(update_fields=["role"])
    with pytest.raises(PermissionDenied):
        access.teacher_test(graph.teacher, graph.draft.pk)
    with pytest.raises(Http404):
        access.student_test(graph.teacher, graph.closed.pk)
    graph.student.role = "ADMIN"
    graph.student.save(update_fields=["role"])
    with pytest.raises(PermissionDenied):
        access.student_result(graph.student, graph.done.pk)
    graph.student.role = "STUDENT"
    graph.student.save(update_fields=["role"])
    assert access.student_result(graph.student, graph.done.pk) == graph.result


# No production URLs are introduced. Exceptions use Django's/DRF's standard
# 403/404 handling; only neutral domain 400/409 errors need a test adapter.
PROBES = {
    "teacher-test": access.teacher_test,
    "teacher-question": access.teacher_question,
    "teacher-option": access.teacher_answer_option,
    "teacher-assignment": access.teacher_assignment,
    "teacher-result": access.teacher_result,
    "student-test": access.student_test,
    "student-attempt": access.student_attempt,
    "student-questions": access.student_questions,
    "student-answers": access.student_answers,
    "student-result": access.student_result,
}


def probe(request, kind, pk):
    try:
        if kind == "selection":
            query = request.GET
            access.student_answer_selection(
                request.user, pk, query.get("question"), query.get("option"),
            )
        else:
            result = PROBES[kind](request.user, pk)
            if hasattr(result, "all"):
                list(result)
    except ValidationError:
        return {"detail": "Invalid related object."}, 400
    except access.LifecycleConflict:
        return {"detail": "Invalid object state."}, 409
    return {"executed": True}, 200


@require_http_methods(["GET", "POST"])
def web_probe(request, kind, pk):
    data, status = probe(request, kind, pk)
    return JsonResponse(data, status=status)


@api_view(["GET", "POST"])
def api_probe(request, kind, pk):
    data, status = probe(request, kind, pk)
    return Response(data, status=status)


urlpatterns = [
    path("probe/web/<str:kind>/<int:pk>/", web_probe),
    path("probe/api/<str:kind>/<int:pk>/", api_probe),
]


@pytest.fixture
def routes(settings):
    settings.ROOT_URLCONF = __name__
    settings.DEBUG = False


@pytest.mark.parametrize("interface", ["web", "api"])
@pytest.mark.parametrize("kind,actor,own,foreign", [
    ("teacher-test", "teacher", "test", "foreign_test"),
    ("teacher-question", "teacher", "question", "foreign_question"),
    ("teacher-option", "teacher", "option", "foreign_option"),
    ("teacher-assignment", "teacher", "assignment", "foreign_assignment"),
    ("teacher-result", "teacher", "result", "foreign_result"),
    ("student-test", "student", "test", "foreign_test"),
    ("student-attempt", "student", "attempt", "other_attempt"),
    ("student-questions", "student", "attempt", "other_attempt"),
    ("student-answers", "student", "attempt", "other_attempt"),
    ("student-result", "student", "done", "other_done"),
])
def test_http_idor_has_indistinguishable_404(graph, routes, interface, kind, actor, own, foreign):
    client = Client(enforce_csrf_checks=True)
    client.force_login(getattr(graph, actor))
    prefix = f"/probe/{interface}/{kind}/"
    assert client.get(f"{prefix}{getattr(graph, own).pk}/").status_code == 200
    denied = client.get(f"{prefix}{getattr(graph, foreign).pk}/")
    missing = client.get(f"{prefix}999999/")
    assert denied.status_code == missing.status_code == 404
    assert denied.content == missing.content
    assert b"executed" not in denied.content


@pytest.mark.parametrize("interface", ["web", "api"])
def test_http_selection_order_neutral_400_and_no_mutation(graph, routes, interface):
    client = Client(enforce_csrf_checks=True)
    client.force_login(graph.student)
    prefix = f"/probe/{interface}/selection/"
    before = list(StudentAnswer.objects.values())
    neutral = []
    for question, option in (
        (graph.foreign_question.pk, graph.foreign_option.pk),
        (graph.question.pk, graph.option2.pk), (999999, 999999),
    ):
        response = client.get(f"{prefix}{graph.attempt.pk}/", {"question": question, "option": option})
        assert response.status_code == 400
        neutral.append(response.content)
    assert len(set(neutral)) == 1
    assert client.get(f"{prefix}{graph.other_attempt.pk}/").status_code == 404
    assert client.get(f"{prefix}{graph.done.pk}/").status_code == 409
    assert list(StudentAnswer.objects.values()) == before


@pytest.mark.parametrize("interface", ["web", "api"])
def test_existing_session_loses_object_access_after_role_change_or_block(graph, routes, interface):
    client = Client(enforce_csrf_checks=True)
    client.force_login(graph.student)
    url = f"/probe/{interface}/student-attempt/{graph.attempt.pk}/"
    assert client.get(url).status_code == 200
    get_user_model().objects.filter(pk=graph.student.pk).update(role="TEACHER")
    assert client.get(url).status_code == 403
    get_user_model().objects.filter(pk=graph.student.pk).update(role="STUDENT", is_active=False)
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("interface", ["web", "api"])
def test_protected_object_post_still_requires_csrf(graph, routes, interface):
    client = Client(enforce_csrf_checks=True)
    client.force_login(graph.student)
    url = f"/probe/{interface}/student-attempt/{graph.attempt.pk}/"
    assert client.post(url).status_code == 403
    token = "a" * 32
    client.cookies["csrftoken"] = token
    assert client.post(url, HTTP_X_CSRFTOKEN=token).status_code == 200
    foreign = f"/probe/{interface}/student-attempt/{graph.other_attempt.pk}/"
    assert client.post(foreign, HTTP_X_CSRFTOKEN=token).status_code == 404


def test_probe_urls_are_not_in_production_urlconf():
    from django.urls import Resolver404, resolve
    with pytest.raises(Resolver404):
        resolve("/probe/api/student-attempt/1/", urlconf="config.urls")
