"""Functional, access, CSRF and atomicity checks for real stage 16 routes."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from assessments import services
from assessments.access import LifecycleConflict
from assessments.models import AnswerOption, Attempt, Question, Result, StudentAnswer, Test as Assessment, TestAssignment as Assignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def data():
    User = get_user_model()
    teacher = User.objects.create_user(username="teacher", password="TeacherPass16!", role="TEACHER")
    other = User.objects.create_user(username="other", role="TEACHER")
    student = User.objects.create_user(username="student", role="STUDENT")
    admin = User.objects.create_user(username="admin", role="ADMIN", is_staff=True, is_superuser=True)
    test = Assessment.objects.create(owner=teacher, title="Security", max_attempts=2)
    foreign = Assessment.objects.create(owner=other, title="Private foreign title")
    question = Question.objects.create(test=test, text="Question", position=1)
    one = AnswerOption.objects.create(question=question, text="One", position=1, is_correct=True)
    two = AnswerOption.objects.create(question=question, text="Two", position=2)
    fq = Question.objects.create(test=foreign, text="Secret question", position=1)
    fo = AnswerOption.objects.create(question=fq, text="Secret option", position=1)
    return dict(teacher=teacher, other=other, student=student, admin=admin, test=test, foreign=foreign, q=question, one=one, two=two, fq=fq, fo=fo)


@pytest.fixture
def api(data):
    client = APIClient()
    client.force_login(data["teacher"])
    return client


def test_url(data, suffix=""):
    return f'/api/teacher/tests/{data["test"].pk}/{suffix}'


# This is a URL helper, not a pytest test.
test_url.__test__ = False


def test_complete_teacher_api_flow(api, data):
    response = api.post('/api/teacher/tests/', {"title": "New"}, format="json")
    assert response.status_code == 201
    t = response.json()
    assert set(t) == {"id", "title", "status", "max_attempts"}
    assert t["status"] == "DRAFT" and t["max_attempts"] == 1
    url = f'/api/teacher/tests/{t["id"]}/'
    assert api.patch(url, {"max_attempts": 3}, format="json").status_code == 200
    assert api.post(url+'activate/').status_code == 409
    q = api.post(url+'questions/', {"text": "Question", "position": 1}, format="json")
    assert q.status_code == 201 and set(q.json()) == {"id", "test_id", "text", "position"}
    option_url = f'/api/teacher/questions/{q.json()["id"]}/answer-options/'
    first = api.post(option_url, {"text": "A", "position": 1, "is_correct": True}, format="json")
    assert first.status_code == 201
    assert api.post(option_url, {"text": "B", "position": 2}, format="json").status_code == 201
    assert api.get(option_url).json()[0]["is_correct"] is True
    assert api.post(url+'assignments/', {"student_id": data["student"].pk}, format="json").status_code == 201
    assert api.post(url+'activate/').status_code == 200
    assert api.get(url).json()["status"] == "ACTIVE"
    assert api.post(url+'close/').status_code == 200
    assert api.get(url).json()["status"] == "CLOSED"
    assert api.delete(url).status_code == 405


READ_PATHS = ["tests/", "students/", "tests/{test}/", "tests/{test}/questions/", "questions/{q}/answer-options/", "tests/{test}/assignments/", "tests/{test}/results/"]
WRITE_PATHS = [("post", "tests/", {"title": "Denied"}), ("patch", "tests/{test}/", {"title": "Denied"}), ("post", "tests/{test}/activate/", {}), ("post", "tests/{test}/close/", {}), ("post", "tests/{test}/questions/", {"text": "Denied", "position": 8}), ("patch", "questions/{q}/", {"text": "Denied"}), ("post", "questions/{q}/answer-options/", {"text": "Denied", "position": 8}), ("patch", "answer-options/{one}/", {"text": "Denied"}), ("post", "tests/{test}/assignments/", {"student_id": 1})]


def path(data, template):
    return '/api/teacher/' + template.format(**{k: v.pk for k, v in data.items()})


@pytest.mark.parametrize("role", [None, "student", "admin"])
@pytest.mark.parametrize("template", READ_PATHS)
def test_read_role_boundaries(data, role, template):
    client = APIClient()
    if role:
        client.force_login(data[role])
    assert client.get(path(data, template)).status_code == 403


@pytest.mark.parametrize("role", [None, "student", "admin"])
@pytest.mark.parametrize("method,template,payload", WRITE_PATHS)
def test_write_role_boundaries(data, role, method, template, payload):
    client = APIClient()
    if role:
        client.force_login(data[role])
    before = (Assessment.objects.count(), Question.objects.count(), AnswerOption.objects.count(), Assignment.objects.count())
    assert getattr(client, method)(path(data, template), payload, format="json").status_code == 403
    assert before == (Assessment.objects.count(), Question.objects.count(), AnswerOption.objects.count(), Assignment.objects.count())


@pytest.mark.parametrize("method,template,payload", WRITE_PATHS)
def test_api_csrf_on_every_write(data, method, template, payload):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(data["teacher"])
    assert getattr(client, method)(path(data, template), payload, format="json").status_code == 403
    token = client.get('/api/auth/csrf/').json()["csrfToken"]
    response = getattr(client, method)(path(data, template), payload, format="json", HTTP_X_CSRFTOKEN=token)
    assert response.status_code != 403


@pytest.mark.parametrize("method,template", [("get", "tests/{test}/"), ("patch", "tests/{test}/"), ("post", "tests/{test}/activate/"), ("post", "tests/{test}/close/"), ("get", "tests/{test}/questions/"), ("post", "tests/{test}/questions/"), ("patch", "questions/{q}/"), ("get", "questions/{q}/answer-options/"), ("post", "questions/{q}/answer-options/"), ("patch", "answer-options/{one}/"), ("get", "tests/{test}/assignments/"), ("post", "tests/{test}/assignments/"), ("get", "tests/{test}/results/")])
def test_foreign_and_missing_are_identical(api, data, method, template):
    def request(ids):
        url = '/api/teacher/' + template.format(**ids)
        return api.get(url) if method == "get" else getattr(api, method)(url, {}, format="json")
    existing = request(dict(test=data["foreign"].pk, q=data["fq"].pk, one=data["fo"].pk))
    missing = request(dict(test=999999, q=999999, one=999999))
    assert existing.status_code == missing.status_code == 404
    assert existing.content == missing.content


@pytest.mark.parametrize("method,template,payload", WRITE_PATHS)
def test_unknown_fields_rejected(api, data, method, template, payload):
    if template.endswith('close/'):
        data["test"].status = "ACTIVE"
        data["test"].save()
    payload = dict(payload, owner_id=data["other"].pk)
    assert getattr(api, method)(path(data, template), payload, format="json").status_code == 400


@pytest.mark.parametrize("state", ["ACTIVE", "CLOSED"])
@pytest.mark.parametrize("method,template,payload", [w for w in WRITE_PATHS if w[1] not in ["tests/", "tests/{test}/assignments/", "tests/{test}/close/"]])
def test_content_is_immutable_after_activation(api, data, state, method, template, payload):
    data["test"].status = state
    data["test"].save()
    assert getattr(api, method)(path(data, template), payload, format="json").status_code == 409
    data["q"].refresh_from_db()
    assert data["q"].text == "Question"


@pytest.mark.parametrize("invalid", [0, -1, True, "bad", 1.2, 2147483648, None])
def test_invalid_numbers(api, invalid):
    assert api.post('/api/teacher/tests/', {"title": "x", "max_attempts": invalid}, format="json").status_code == 400


def test_list_projections_and_result_privacy(api, data):
    assert [t["id"] for t in api.get('/api/teacher/tests/').json()] == [data["test"].pk]
    assert api.get('/api/teacher/students/').json() == [{"id": data["student"].pk, "username": "student"}]
    assignment = Assignment.objects.create(test=data["test"], student=data["student"])
    attempt = Attempt.objects.create(assignment=assignment, started_at=timezone.now(), completed_at=timezone.now())
    StudentAnswer.objects.create(attempt=attempt, question=data["q"], answer_option=data["one"])
    result = Result.objects.create(attempt=attempt, score_points=1, correct_percentage="100.00")
    assert api.get(test_url(data, 'results/')).json() == [{"id": result.pk, "student_id": data["student"].pk, "score_points": 1, "correct_percentage": "100.00"}]
    assert set(api.get(test_url(data, 'assignments/')).json()[0]) == {"id", "test_id", "student_id"}
    for endpoint in ['attempts/', 'student-answers/']:
        assert api.get('/api/teacher/'+endpoint).status_code == 404


def test_assignments_and_repeated_actions(api, data):
    url = test_url(data, 'assignments/')
    invalid_responses = []
    for target in [data["teacher"].pk, data["admin"].pk, 99999]:
        response = api.post(url, {"student_id": target}, format="json")
        assert response.status_code == 400
        invalid_responses.append(response.content)
    data["student"].is_active = False
    data["student"].save()
    response = api.post(url, {"student_id": data["student"].pk}, format="json")
    assert response.status_code == 400 and response.content in invalid_responses
    assert api.get('/api/teacher/students/').json() == []
    data["student"].is_active = True
    data["student"].save()
    assert api.post(url, {"student_id": data["student"].pk}, format="json").status_code == 201
    assert api.post(url, {"student_id": data["student"].pk}, format="json").status_code == 409
    assert api.post(test_url(data, 'activate/')).status_code == 200
    assert api.post(test_url(data, 'activate/')).status_code == 409
    attempt = Attempt.objects.create(assignment=Assignment.objects.get(test=data["test"]), started_at=timezone.now())
    assert api.post(test_url(data, 'close/')).status_code == 200
    assert api.post(test_url(data, 'close/')).status_code == 409
    assert api.post(url, {"student_id": data["student"].pk}, format="json").status_code == 409
    attempt.refresh_from_db()
    assert attempt.completed_at is None and not Result.objects.filter(attempt=attempt).exists()


def test_correct_option_and_position_conflicts(api, data):
    url = f'/api/teacher/answer-options/{data["two"].pk}/'
    assert api.patch(url, {"is_correct": True}, format="json").status_code == 409
    assert api.patch(url, {"position": 1}, format="json").status_code == 409
    assert api.patch(url, {"is_correct": "false"}, format="json").status_code == 400
    assert api.patch(f'/api/teacher/answer-options/{data["one"].pk}/', {"is_correct": False}, format="json").status_code == 200
    assert api.post(test_url(data, 'activate/')).status_code == 409
    assert api.patch(url, {"is_correct": True}, format="json").status_code == 200
    assert api.post(test_url(data, 'activate/')).status_code == 200


@pytest.mark.parametrize("change", ["role", "is_active"])
def test_existing_session_uses_current_role(api, data, change):
    get_user_model().objects.filter(pk=data["teacher"].pk).update(**{change: "STUDENT" if change == "role" else False})
    assert api.get('/api/teacher/tests/').status_code == 403
    assert api.patch(test_url(data), {"title": "Denied"}, format="json").status_code == 403
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        services.update_test(data["teacher"], data["test"].pk, {"title": "Denied"})


def editor_payload(data):
    return {"text": "Edited", "position": "1", "correct": "1", "options-TOTAL_FORMS": "2", "options-INITIAL_FORMS": "2", "options-MIN_NUM_FORMS": "0", "options-MAX_NUM_FORMS": "1000", "options-0-id": str(data["one"].pk), "options-0-text": "First", "options-0-position": "2", "options-1-id": str(data["two"].pk), "options-1-text": "Second", "options-1-position": "1"}


def test_html_atomic_editor_and_id_tampering(client, data):
    client.force_login(data["teacher"])
    url = reverse('teacher:question-edit', args=[data["test"].pk, data["q"].pk])
    payload = editor_payload(data)
    assert client.post(url, payload).status_code == 302
    data["one"].refresh_from_db(); data["two"].refresh_from_db()
    assert not data["one"].is_correct and data["two"].is_correct
    assert (data["one"].position, data["two"].position) == (2, 1)
    payload["options-1-id"] = str(data["fo"].pk)
    payload["text"] = "Must not save"
    assert client.post(url, payload).status_code == 400
    data["q"].refresh_from_db()
    assert data["q"].text == "Edited"
    payload["options-1-id"] = str(data["two"].pk)
    payload["options-TOTAL_FORMS"] = "1"
    assert client.post(url, payload).status_code == 400
    assert data["q"].answeroption_set.count() == 2


def test_editor_rolls_back_partial_write(data, monkeypatch):
    old_save = AnswerOption.save
    def broken_save(self, *args, **kwargs):
        if self.text == "Failure":
            raise RuntimeError("Simulated storage failure")
        return old_save(self, *args, **kwargs)
    monkeypatch.setattr(AnswerOption, "save", broken_save)
    rows = [{"id": data["one"].pk, "text": "Changed", "position": 2, "is_correct": False}, {"id": data["two"].pk, "text": "Failure", "position": 1, "is_correct": True}]
    with pytest.raises(RuntimeError):
        services.save_question_editor(data["teacher"], data["test"].pk, data["q"].pk, {"text": "Changed", "position": 1}, rows)
    data["q"].refresh_from_db(); data["one"].refresh_from_db()
    assert data["q"].text == "Question" and data["one"].text == "One"
    assert data["one"].position == 1 and data["one"].is_correct


HTML_ROUTES = [('test-list', []), ('test-create', []), ('test-detail', ['test']), ('test-edit', ['test']), ('question-create', ['test']), ('question-edit', ['test','q']), ('assignments', ['test']), ('results', ['test']), ('test-activate', ['test'])]


@pytest.mark.parametrize("name,keys", HTML_ROUTES)
def test_html_pages_render_and_deny_admin(client, data, name, keys):
    url = reverse('teacher:'+name, args=[data[k].pk for k in keys])
    client.force_login(data["teacher"])
    assert client.get(url).status_code == 200
    client.force_login(data["admin"])
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("name,keys", [r for r in HTML_ROUTES if r[0] not in ['test-list', 'test-detail', 'results']])
def test_html_csrf(client, data, name, keys):
    secure = Client(enforce_csrf_checks=True)
    secure.force_login(data["teacher"])
    url = reverse('teacher:'+name, args=[data[k].pk for k in keys])
    assert secure.post(url, {}).status_code == 403


def test_html_xss_foreign_404_and_immutable_state(client, data):
    client.force_login(data["teacher"])
    data["test"].title = '<script>alert("secret")</script>'
    data["test"].save()
    assert b'&lt;script&gt;' in client.get(reverse('teacher:test-detail', args=[data["test"].pk])).content
    one = client.get(reverse('teacher:test-detail', args=[data["foreign"].pk]))
    two = client.get(reverse('teacher:test-detail', args=[999999]))
    assert one.status_code == two.status_code == 404
    # The logout form contains a freshly masked CSRF token on each response.
    assert one.content.split(b'<main', 1)[1] == two.content.split(b'<main', 1)[1]
    services.activate_test(data["teacher"], data["test"].pk, {})
    assert client.post(reverse('teacher:test-edit', args=[data["test"].pk]), {"title": "Denied", "max_attempts": 1}).status_code == 409
    close_url = reverse('teacher:test-close', args=[data["test"].pk])
    assert client.get(close_url).status_code == 200
    data["test"].refresh_from_db()
    assert data["test"].status == 'ACTIVE'
    assert client.post(close_url).status_code == 302


def test_web_login_logout_real_sessions_and_csrf(data):
    client = Client(enforce_csrf_checks=True)
    assert client.post('/login/', {"username": "teacher", "password": "TeacherPass16!"}).status_code == 403
    assert client.get('/login/').status_code == 200
    token = client.cookies['csrftoken'].value
    assert client.post('/login/', {"username": "teacher", "password": "bad", "csrfmiddlewaretoken": token}).status_code == 401
    assert client.post('/login/', {"username": "teacher", "password": "TeacherPass16!", "csrfmiddlewaretoken": token}).status_code == 302
    assert client.get('/teacher/tests/').status_code == 200
    assert client.get('/logout/').status_code == 405
    assert client.post('/logout/').status_code == 403
    assert client.post('/logout/', {"csrfmiddlewaretoken": client.cookies['csrftoken'].value}).status_code == 302
    assert client.get('/teacher/tests/').status_code == 403
