"""Server-rendered teacher pages; contexts contain only explicit projections."""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.access import assignable_students
from accounts.permissions import require_role
from assessments import access, services
from assessments.forms import AssignmentForm, OptionFormSet, QuestionForm, TestForm
from assessments.serializers import TeacherAssignment, TeacherOption, TeacherQuestion, TeacherResult, TeacherTest


def teacher_page(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return require_role("TEACHER")(view)(request, *args, **kwargs)
        except PermissionDenied:
            return render(request, "assessments/error.html", {"code": 403, "title": "Доступ запрещен"}, status=403)
        except Http404:
            return render(request, "assessments/error.html", {"code": 404, "title": "Страница не найдена"}, status=404)
        except access.LifecycleConflict:
            return render(request, "assessments/error.html", {"code": 409, "title": "Действие невозможно"}, status=409)
        except ValidationError:
            return render(request, "assessments/error.html", {"code": 400, "title": "Проверьте данные"}, status=400)
    return wrapped


def check_fields(request, allowed):
    if set(request.POST) - set(allowed) - {"csrfmiddlewaretoken"}:
        raise ValidationError("Invalid request body.")


def draft_test(request, test_id):
    test = access.teacher_test(request.user, test_id)
    if test.status != "DRAFT":
        raise access.LifecycleConflict
    return test


@teacher_page
@require_http_methods(["GET"])
def test_list(request):
    tests = TeacherTest(access.teacher_tests(request.user).order_by("pk"), many=True).data
    return render(request, "assessments/test_list.html", {"title": "Мои тесты", "tests": tests})


@teacher_page
@require_http_methods(["GET", "POST"])
def test_form(request, test_id=None):
    test = draft_test(request, test_id) if test_id else None
    initial = TeacherTest(test).data if test else None
    form = TestForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST":
        check_fields(request, form.fields)
        if form.is_valid():
            if test:
                test = services.update_test(request.user, test.pk, form.cleaned_data)
            else:
                test = services.create_test(request.user, form.cleaned_data)
            messages.success(request, "Тест сохранен.")
            return redirect("teacher:test-detail", test_id=test.pk)
    return render(request, "assessments/test_form.html", {"title": "Параметры теста" if test else "Новый тест", "form": form, "test": initial}, status=400 if form.is_bound and form.errors else 200)


@teacher_page
@require_http_methods(["GET"])
def test_detail(request, test_id):
    test = access.teacher_test(request.user, test_id)
    questions = []
    for question in access.teacher_questions(request.user, test.pk).prefetch_related("answeroption_set"):
        item = dict(TeacherQuestion(question).data)
        item["options"] = TeacherOption(question.answeroption_set.all().order_by("position"), many=True).data
        item["ready"] = len(item["options"]) >= 2 and sum(o["is_correct"] for o in item["options"]) == 1
        questions.append(item)
    return render(request, "assessments/test_detail.html", {"title": test.title, "test": TeacherTest(test).data, "questions": questions, "ready": services.readiness(test)})


@teacher_page
@require_http_methods(["GET", "POST"])
def test_action(request, test_id, action):
    test = access.teacher_test(request.user, test_id)
    expected = "DRAFT" if action == "activate" else "ACTIVE"
    if test.status != expected:
        raise access.LifecycleConflict
    if request.method == "POST":
        check_fields(request, ())
        operation = services.activate_test if action == "activate" else services.close_test
        operation(request.user, test_id, {})
        messages.success(request, "Тест активирован." if action == "activate" else "Тест закрыт.")
        return redirect("teacher:test-detail", test_id=test_id)
    return render(request, "assessments/test_action.html", {"title": "Подтверждение активации" if action == "activate" else "Закрыть тест?", "test": TeacherTest(test).data, "action": action, "ready": services.readiness(test)})


@teacher_page
@require_http_methods(["GET", "POST"])
def question_form(request, test_id, question_id=None):
    test = draft_test(request, test_id)
    question = access.teacher_question(request.user, question_id) if question_id else None
    if question and question.test_id != test.pk:
        raise Http404
    initial = TeacherQuestion(question).data if question else {"position": (test.question_set.aggregate(n=Max("position"))["n"] or 0) + 1}
    options = list(TeacherOption(access.teacher_answer_options(request.user, question.pk), many=True).data) if question else [{"position": 1}, {"position": 2}]
    payload = request.POST if request.method == "POST" else None
    form = QuestionForm(payload, initial=initial)
    formset = OptionFormSet(payload, initial=options, prefix="options")
    correct = request.POST.get("correct", "") if payload is not None else next((str(i) for i, o in enumerate(options) if o.get("is_correct")), "")
    error = None
    response_status = 200
    if request.method == "POST":
        allowed = set(form.fields) | {"correct"} | {f"options-{name}" for name in formset.management_form.fields}
        allowed |= {f"options-{i}-{name}" for i in range(formset.total_form_count()) for name in ("id", "text", "position")}
        check_fields(request, allowed)
        form_ok, options_ok = form.is_valid(), formset.is_valid()
        if form_ok and options_ok:
            try:
                if correct and (not correct.isdigit() or int(correct) >= len(formset.forms)):
                    raise ValidationError("Invalid correct option.")
                rows = [dict(f.cleaned_data, is_correct=str(i) == correct) for i, f in enumerate(formset.forms) if f.cleaned_data]
                if correct and not formset.forms[int(correct)].cleaned_data:
                    raise ValidationError("Invalid correct option.")
                services.save_question_editor(request.user, test.pk, question_id, form.cleaned_data, rows)
            except (ValidationError, access.LifecycleConflict) as exc:
                error = "Проверьте варианты и уникальность позиций. При изменении данных в другой вкладке обновите страницу."
                response_status = 409 if isinstance(exc, access.LifecycleConflict) else 400
            else:
                messages.success(request, "Вопрос сохранен.")
                return redirect("teacher:test-detail", test_id=test.pk)
        else:
            response_status = 400
    return render(request, "assessments/question_form.html", {"title": "Редактирование вопроса" if question else "Новый вопрос", "test": TeacherTest(test).data, "form": form, "formset": formset, "correct": correct, "error": error}, status=response_status)


@teacher_page
@require_http_methods(["GET", "POST"])
def assignments(request, test_id):
    test = access.teacher_test(request.user, test_id)
    students = list(assignable_students(request.user).order_by("username", "pk"))
    form = AssignmentForm(request.POST if request.method == "POST" else None, students=students)
    response_status = 200
    if request.method == "POST":
        if test.status == "CLOSED":
            raise access.LifecycleConflict
        check_fields(request, form.fields)
        if form.is_valid():
            try:
                services.create_assignment(request.user, test_id, form.cleaned_data)
            except ValidationError:
                form.add_error(None, "Некорректные данные студента.")
                response_status = 400
            except access.LifecycleConflict:
                form.add_error(None, "Назначение уже существует или тест закрыт.")
                response_status = 409
            else:
                messages.success(request, "Тест назначен.")
                return redirect("teacher:assignments", test_id=test_id)
        else:
            response_status = 400
    rows = TeacherAssignment(access.teacher_assignments(request.user, test_id).order_by("pk"), many=True).data
    return render(request, "assessments/assignments.html", {"title": "Назначения", "test": TeacherTest(test).data, "form": form, "assignments": rows, "has_students": bool(students)}, status=response_status)


@teacher_page
@require_http_methods(["GET"])
def results(request, test_id):
    test = access.teacher_test(request.user, test_id)
    rows = access.teacher_results(request.user, test_id).select_related("attempt__assignment").order_by("pk")
    return render(request, "assessments/results.html", {"title": "Результаты теста", "test": TeacherTest(test).data, "results": TeacherResult(rows, many=True).data})
