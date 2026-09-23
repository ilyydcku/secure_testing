"""Stage 16 writes shared by API and HTML; no student/admin operations.

All lifecycle-dependent writes lock Test and recheck access/state afterwards.
Activation additionally locks its owner first, matching change_user_role.
Assignment locks the eligible student after Test, then rechecks eligibility.
The HTML question editor is one atomic operation, including all its options.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import ValidationError

from accounts.permissions import check_role
from assessments import access
from assessments.models import AnswerOption, Question, Test, TestAssignment
from assessments.serializers import AssignmentInput, OptionInput, QuestionInput, TestInput


def current_teacher(user, *, lock=False):
    check_role(user, "TEACHER")
    users = get_user_model().objects
    if lock:
        users = users.select_for_update()
    fresh = users.filter(pk=user.pk).first()
    if fresh is None:
        raise PermissionDenied
    check_role(fresh, "TEACHER")
    return fresh


def locked_test(user, test_id, states):
    check_role(user, "TEACHER")
    test = access._get(Test.objects.select_for_update().filter(owner_id=user.pk), pk=test_id)
    current_teacher(user)
    if test.status not in states:
        raise access.LifecycleConflict("Operation is not allowed in the current state.")
    return test


def validated(cls, data, *, partial=False):
    serializer = cls(data=data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def save_fields(obj, data):
    for key, value in data.items():
        setattr(obj, key, value)
    if data:
        obj.save(update_fields=list(data))
    return obj


def check_position(model, parent, position, exclude=None):
    if model.objects.filter(**parent, position=position).exclude(pk=exclude).exists():
        raise access.LifecycleConflict("Position is already in use.")


@transaction.atomic
def create_test(user, data):
    user = current_teacher(user)
    return Test.objects.create(owner=user, status="DRAFT", **validated(TestInput, data))


@transaction.atomic
def update_test(user, test_id, data):
    test = locked_test(user, test_id, ("DRAFT",))
    return save_fields(test, validated(TestInput, data, partial=True))


def readiness(test):
    questions = list(test.question_set.prefetch_related("answeroption_set").order_by("position"))
    return bool(questions) and all(
        q.text.strip() and len(q.answeroption_set.all()) >= 2
        and all(o.text.strip() for o in q.answeroption_set.all())
        and sum(o.is_correct for o in q.answeroption_set.all()) == 1
        for q in questions
    )


def empty_body(data):
    if data != {}:
        raise ValidationError("This operation does not accept a request body.")


@transaction.atomic
def activate_test(user, test_id, data):
    user = current_teacher(user, lock=True)
    test = locked_test(user, test_id, ("DRAFT",))
    empty_body(data)
    if not readiness(test):
        raise access.LifecycleConflict("Test is not ready for activation.")
    return save_fields(test, {"status": "ACTIVE"})


@transaction.atomic
def close_test(user, test_id, data):
    test = locked_test(user, test_id, ("ACTIVE",))
    empty_body(data)
    # Existing attempts and their answers are deliberately untouched.
    return save_fields(test, {"status": "CLOSED"})


@transaction.atomic
def create_question(user, test_id, data):
    test = locked_test(user, test_id, ("DRAFT",))
    values = validated(QuestionInput, data)
    check_position(Question, {"test": test}, values["position"])
    return Question.objects.create(test=test, **values)


@transaction.atomic
def update_question(user, question_id, data):
    initial = access.teacher_question(user, question_id)
    test = locked_test(user, initial.test_id, ("DRAFT",))
    question = access._get(Question.objects.filter(test=test), pk=question_id)
    values = validated(QuestionInput, data, partial=True)
    check_position(Question, {"test": test}, values.get("position", question.position), question.pk)
    return save_fields(question, values)


def check_option(question, values, existing=None):
    check_position(AnswerOption, {"question": question}, values.get("position", getattr(existing, "position", None)), getattr(existing, "pk", None))
    if values.get("is_correct", getattr(existing, "is_correct", False)) and question.answeroption_set.filter(is_correct=True).exclude(pk=getattr(existing, "pk", None)).exists():
        raise access.LifecycleConflict("A correct option is already set.")


@transaction.atomic
def create_option(user, question_id, data):
    initial = access.teacher_question(user, question_id)
    test = locked_test(user, initial.test_id, ("DRAFT",))
    question = access._get(Question.objects.filter(test=test), pk=question_id)
    values = validated(OptionInput, data)
    check_option(question, values)
    return AnswerOption.objects.create(question=question, **values)


@transaction.atomic
def update_option(user, option_id, data):
    initial = access.teacher_answer_option(user, option_id)
    test = locked_test(user, initial.question.test_id, ("DRAFT",))
    option = access._get(AnswerOption.objects.filter(question__test=test), pk=option_id)
    values = validated(OptionInput, data, partial=True)
    check_option(option.question, values, option)
    return save_fields(option, values)


@transaction.atomic
def create_assignment(user, test_id, data):
    test = locked_test(user, test_id, ("DRAFT", "ACTIVE"))
    values = validated(AssignmentInput, data)
    student = get_user_model().objects.select_for_update().filter(
        pk=values["student_id"], role="STUDENT", is_active=True,
    ).first()
    if student is None:
        raise ValidationError("Invalid related object.")
    if TestAssignment.objects.filter(test=test, student=student).exists():
        raise access.LifecycleConflict("Assignment already exists.")
    return TestAssignment.objects.create(test=test, student=student)


@transaction.atomic
def save_question_editor(user, test_id, question_id, data, options):
    """Explicitly save every option from the HTML form, without deletion.

API PATCH remains single-resource. This HTML aggregate operation allows a
radio-button change and position swaps without exposing a partial save.
Untrusted option ids must exactly cover the existing question's options.
"""
    test = locked_test(user, test_id, ("DRAFT",))
    question = None
    if question_id is not None:
        question = access._get(Question.objects.filter(test=test), pk=question_id)
    values = validated(QuestionInput, data)
    check_position(Question, {"test": test}, values["position"], question_id)
    existing = {o.pk: o for o in question.answeroption_set.all()} if question else {}
    submitted = [row.get("id") for row in options if row.get("id") is not None]
    if len(submitted) != len(set(submitted)) or set(submitted) != set(existing):
        raise ValidationError("Invalid related object.")
    rows = [(row.get("id"), validated(OptionInput, {k: v for k, v in row.items() if k != "id"})) for row in options]
    positions = [v["position"] for _, v in rows]
    if len(positions) != len(set(positions)) or sum(v["is_correct"] for _, v in rows) > 1:
        raise ValidationError("Option positions must be unique; select at most one correct option.")
    if question:
        save_fields(question, values)
    else:
        question = Question.objects.create(test=test, **values)
    # Park existing positions at unused valid values; preserve ids and FKs.
    used = set(positions) | {o.position for o in existing.values()}
    temporary = 1
    question.answeroption_set.filter(is_correct=True).update(is_correct=False)
    for option in existing.values():
        while temporary in used:
            temporary += 1
        option.position = temporary
        option.save(update_fields=["position"])
        used.add(temporary)
    for pk, row in rows:
        if pk is None:
            AnswerOption.objects.create(question=question, **row)
        else:
            save_fields(existing[pk], row)
    return question
