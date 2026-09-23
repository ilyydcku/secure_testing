from django.urls import include, path
from django.views.generic import RedirectView

from accounts import web

urlpatterns = [
    path("api/auth/", include("accounts.urls")),
    path("api/teacher/", include("assessments.api_urls")),
    path("teacher/", include("assessments.urls")),
    path("login/", web.login_page, name="login"),
    path("logout/", web.logout_page, name="logout"),
    path("", RedirectView.as_view(pattern_name="login", permanent=False)),
]
