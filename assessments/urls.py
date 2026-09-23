from django.urls import path

from assessments import views

app_name = "teacher"
urlpatterns = [
    path("tests/", views.test_list, name="test-list"),
    path("tests/new/", views.test_form, name="test-create"),
    path("tests/<int:test_id>/", views.test_detail, name="test-detail"),
    path("tests/<int:test_id>/edit/", views.test_form, name="test-edit"),
    path("tests/<int:test_id>/activate/", views.test_action, {"action": "activate"}, name="test-activate"),
    path("tests/<int:test_id>/close/", views.test_action, {"action": "close"}, name="test-close"),
    path("tests/<int:test_id>/questions/new/", views.question_form, name="question-create"),
    path("tests/<int:test_id>/questions/<int:question_id>/", views.question_form, name="question-edit"),
    path("tests/<int:test_id>/assignments/", views.assignments, name="assignments"),
    path("tests/<int:test_id>/results/", views.results, name="results"),
]
