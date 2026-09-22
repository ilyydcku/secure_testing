from django.conf import settings
from django.db import models


class Test(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=20, default="DRAFT")
    max_attempts = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["DRAFT", "ACTIVE", "CLOSED"]),
                name="assessments_test_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1),
                name="assessments_test_max_attempts_gte_1",
            ),
        ]


class Question(models.Model):
    test = models.ForeignKey(Test, on_delete=models.PROTECT)
    text = models.TextField()
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="assessments_question_position_gte_1",
            ),
            models.UniqueConstraint(
                fields=["test", "position"],
                name="assessments_question_test_position_unique",
            ),
        ]


class AnswerOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    text = models.TextField()
    position = models.PositiveIntegerField()
    is_correct = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="assessments_answeroption_position_gte_1",
            ),
            models.UniqueConstraint(
                fields=["question", "position"],
                name="assessments_answeroption_question_position_unique",
            ),
            models.UniqueConstraint(
                fields=["question"],
                condition=models.Q(is_correct=True),
                name="assessments_answeroption_one_correct",
            ),
        ]


class TestAssignment(models.Model):
    test = models.ForeignKey(Test, on_delete=models.PROTECT)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["test", "student"],
                name="assessments_assignment_test_student_unique",
            ),
        ]


class Attempt(models.Model):
    assignment = models.ForeignKey(TestAssignment, on_delete=models.PROTECT)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(completed_at__isnull=True)
                    | models.Q(completed_at__gte=models.F("started_at"))
                ),
                name="assessments_attempt_completed_after_started",
            ),
            models.UniqueConstraint(
                fields=["assignment"],
                condition=models.Q(completed_at__isnull=True),
                name="assessments_attempt_one_in_progress",
            ),
        ]


class StudentAnswer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.PROTECT)
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    answer_option = models.ForeignKey(AnswerOption, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"],
                name="assessments_studentanswer_attempt_question_unique",
            ),
        ]


class Result(models.Model):
    attempt = models.OneToOneField(Attempt, on_delete=models.PROTECT)
    score_points = models.PositiveIntegerField()
    correct_percentage = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(score_points__gte=0),
                name="assessments_result_score_points_gte_0",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(correct_percentage__gte=0)
                    & models.Q(correct_percentage__lte=100)
                ),
                name="assessments_result_percentage_0_100",
            ),
        ]
