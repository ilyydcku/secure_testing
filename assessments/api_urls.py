from django.urls import path

from assessments import api

urlpatterns = [
    path("tests/", api.Tests.as_view()),
    path("tests/<int:test_id>/", api.TestDetail.as_view()),
    path("tests/<int:test_id>/activate/", api.TestAction.as_view(), {"action": "activate"}),
    path("tests/<int:test_id>/close/", api.TestAction.as_view(), {"action": "close"}),
    path("tests/<int:test_id>/questions/", api.Questions.as_view()),
    path("questions/<int:question_id>/", api.QuestionDetail.as_view()),
    path("questions/<int:question_id>/answer-options/", api.Options.as_view()),
    path("answer-options/<int:option_id>/", api.OptionDetail.as_view()),
    path("students/", api.Students.as_view()),
    path("tests/<int:test_id>/assignments/", api.Assignments.as_view()),
    path("tests/<int:test_id>/results/", api.Results.as_view()),
]
