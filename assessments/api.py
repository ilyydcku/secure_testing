"""Teacher DRF endpoints. SessionAuthentication retains standard CSRF checks."""

from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.access import assignable_students
from accounts.permissions import IsTeacher
from assessments import access, services
from assessments.serializers import TeacherAssignment, TeacherOption, TeacherQuestion, TeacherResult, TeacherTest


class TeacherView(APIView):
    permission_classes = [IsTeacher]

    def handle_exception(self, exc):
        if isinstance(exc, access.LifecycleConflict):
            return Response({"detail": str(exc)}, status=409)
        return super().handle_exception(exc)


class Tests(TeacherView):
    def get(self, request):
        return Response(TeacherTest(access.teacher_tests(request.user).order_by("pk"), many=True).data)

    def post(self, request):
        return Response(TeacherTest(services.create_test(request.user, request.data)).data, status=201)


class TestDetail(TeacherView):
    def get(self, request, test_id):
        return Response(TeacherTest(access.teacher_test(request.user, test_id)).data)

    def patch(self, request, test_id):
        return Response(TeacherTest(services.update_test(request.user, test_id, request.data)).data)


class TestAction(TeacherView):
    def post(self, request, test_id, action):
        operation = services.activate_test if action == "activate" else services.close_test
        return Response(TeacherTest(operation(request.user, test_id, request.data)).data)


class Questions(TeacherView):
    def get(self, request, test_id):
        return Response(TeacherQuestion(access.teacher_questions(request.user, test_id), many=True).data)

    def post(self, request, test_id):
        return Response(TeacherQuestion(services.create_question(request.user, test_id, request.data)).data, status=201)


class QuestionDetail(TeacherView):
    def patch(self, request, question_id):
        return Response(TeacherQuestion(services.update_question(request.user, question_id, request.data)).data)


class Options(TeacherView):
    def get(self, request, question_id):
        return Response(TeacherOption(access.teacher_answer_options(request.user, question_id), many=True).data)

    def post(self, request, question_id):
        return Response(TeacherOption(services.create_option(request.user, question_id, request.data)).data, status=201)


class OptionDetail(TeacherView):
    def patch(self, request, option_id):
        return Response(TeacherOption(services.update_option(request.user, option_id, request.data)).data)


class Students(TeacherView):
    def get(self, request):
        return Response(list(assignable_students(request.user).order_by("username", "pk")))


class Assignments(TeacherView):
    def get(self, request, test_id):
        return Response(TeacherAssignment(access.teacher_assignments(request.user, test_id).order_by("pk"), many=True).data)

    def post(self, request, test_id):
        return Response(TeacherAssignment(services.create_assignment(request.user, test_id, request.data)).data, status=201)


class Results(TeacherView):
    def get(self, request, test_id):
        rows = access.teacher_results(request.user, test_id).select_related("attempt__assignment").order_by("pk")
        return Response(TeacherResult(rows, many=True).data)
