from django.urls import path

from accounts import api

urlpatterns = [
    path("csrf/", api.csrf_view, name="auth-csrf"),
    path("login/", api.login_view, name="auth-login"),
    path("logout/", api.logout_view, name="auth-logout"),
    path("me/", api.me_view, name="auth-me"),
]
