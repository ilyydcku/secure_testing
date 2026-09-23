"""Explicit teacher-only input and output boundaries."""

from collections.abc import Mapping

from rest_framework import serializers


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, Mapping) or set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Invalid request body."]})
        return super().to_internal_value(data)


class PositiveInteger(serializers.IntegerField):
    def __init__(self, **kwargs):
        super().__init__(min_value=1, max_value=2147483647, **kwargs)

    def to_internal_value(self, data):
        if isinstance(data, bool):
            self.fail("invalid")
        return super().to_internal_value(data)


class Boolean(serializers.BooleanField):
    def to_internal_value(self, data):
        if not isinstance(data, bool):
            self.fail("invalid", input=data)
        return data


class TestInput(StrictInput):
    title = serializers.CharField(max_length=255)
    max_attempts = PositiveInteger(default=1)


class QuestionInput(StrictInput):
    text = serializers.CharField()
    position = PositiveInteger()


class OptionInput(QuestionInput):
    is_correct = Boolean(default=False)


class AssignmentInput(StrictInput):
    student_id = serializers.IntegerField(min_value=1, max_value=9223372036854775807)


class TeacherTest(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    status = serializers.CharField()
    max_attempts = serializers.IntegerField()


class TeacherQuestion(serializers.Serializer):
    id = serializers.IntegerField()
    test_id = serializers.IntegerField()
    text = serializers.CharField()
    position = serializers.IntegerField()


class TeacherOption(serializers.Serializer):
    id = serializers.IntegerField()
    question_id = serializers.IntegerField()
    text = serializers.CharField()
    position = serializers.IntegerField()
    is_correct = serializers.BooleanField()


class TeacherAssignment(serializers.Serializer):
    id = serializers.IntegerField()
    test_id = serializers.IntegerField()
    student_id = serializers.IntegerField()


class TeacherResult(serializers.Serializer):
    id = serializers.IntegerField()
    student_id = serializers.IntegerField(source="attempt.assignment.student_id")
    score_points = serializers.IntegerField()
    correct_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
