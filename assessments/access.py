"""Shared object scopes for Django and DRF (stage 15).

Call with the current request.user. Role checks precede object queries.
These helpers return internal querysets/models, never response payloads.
Future writers must recheck access/state inside their transaction after locking
the relevant rows. A prior read with these helpers is not a write permission.
"""

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import F
from django.http import Http404

from accounts.permissions import check_role
from assessments.models import (
    AnswerOption, Attempt, Question, Result, StudentAnswer, Test, TestAssignment,
)


class LifecycleConflict(Exception):
    """An accessible object's state disallows the operation (HTTP 409)."""


def _get(queryset, **lookup):
    try:
        return queryset.get(**lookup)
    except ObjectDoesNotExist:
        raise Http404("Not found.") from None


def teacher_tests(user):
    check_role(user, "TEACHER")
    return Test.objects.filter(owner_id=user.pk)


def teacher_test(user, test_id):
    return _get(teacher_tests(user), pk=test_id)


def teacher_questions(user, test_id):
    test = teacher_test(user, test_id)
    return Question.objects.filter(test=test).order_by("position")


def teacher_question(user, question_id):
    check_role(user, "TEACHER")
    return _get(Question.objects.filter(test__owner_id=user.pk), pk=question_id)


def teacher_answer_options(user, question_id):
    question = teacher_question(user, question_id)
    return AnswerOption.objects.filter(question=question).order_by("position")


def teacher_answer_option(user, option_id):
    check_role(user, "TEACHER")
    return _get(
        AnswerOption.objects.filter(question__test__owner_id=user.pk), pk=option_id,
    )


def teacher_assignments(user, test_id):
    test = teacher_test(user, test_id)
    return TestAssignment.objects.filter(test=test)


def teacher_assignment(user, assignment_id):
    check_role(user, "TEACHER")
    return _get(
        TestAssignment.objects.filter(test__owner_id=user.pk), pk=assignment_id,
    )


def teacher_results(user, test_id):
    test = teacher_test(user, test_id)
    return Result.objects.filter(
        attempt__assignment__test=test, attempt__completed_at__isnull=False,
    )


def teacher_result(user, result_id):
    check_role(user, "TEACHER")
    return _get(Result.objects.filter(
        attempt__assignment__test__owner_id=user.pk,
        attempt__completed_at__isnull=False,
    ), pk=result_id)


def student_tests(user):
    check_role(user, "STUDENT")
    return Test.objects.filter(
        testassignment__student_id=user.pk, status__in=("ACTIVE", "CLOSED"),
    ).distinct()


def student_test(user, test_id):
    return _get(student_tests(user), pk=test_id)


def student_attempts(user, test_id):
    test = student_test(user, test_id)
    return Attempt.objects.filter(
        assignment__student_id=user.pk, assignment__test=test,
    ).order_by("-started_at", "-pk")


def student_attempt(user, attempt_id):
    check_role(user, "STUDENT")
    return _get(Attempt.objects.filter(
        assignment__student_id=user.pk,
        assignment__test__status__in=("ACTIVE", "CLOSED"),
    ).select_related("assignment"), pk=attempt_id)


def student_in_progress_attempt(user, attempt_id):
    attempt = student_attempt(user, attempt_id)
    if attempt.completed_at is not None:
        raise LifecycleConflict("Attempt is already completed.")
    return attempt


def student_questions(user, attempt_id):
    attempt = student_in_progress_attempt(user, attempt_id)
    return Question.objects.filter(
        test_id=attempt.assignment.test_id,
    ).order_by("position")


def student_answers(user, attempt_id):
    attempt = student_in_progress_attempt(user, attempt_id)
    # Defensive filtering also excludes inconsistent cross-table links.
    return StudentAnswer.objects.filter(
        attempt=attempt, question__test_id=attempt.assignment.test_id,
        answer_option__question_id=F("question_id"),
    )


def student_answer_selection(user, attempt_id, question_id, answer_option_id):
    """Validate ownership/state first, then both supplied links, without writes.

    This validates a selection only. The save operation and its Attempt lock
    belong to stage 17. Never serialize the returned AnswerOption wholesale.
    """
    attempt = student_in_progress_attempt(user, attempt_id)
    try:
        question = Question.objects.get(
            pk=question_id, test_id=attempt.assignment.test_id,
        )
        option = AnswerOption.objects.get(
            pk=answer_option_id, question_id=question.pk,
        )
    except (ObjectDoesNotExist, ValueError, TypeError):
        raise ValidationError("Invalid related object.") from None
    return attempt, question, option


def student_result(user, attempt_id):
    attempt = student_attempt(user, attempt_id)
    if attempt.completed_at is None:
        raise LifecycleConflict("Attempt is not completed.")
    return _get(Result.objects.all(), attempt=attempt)
