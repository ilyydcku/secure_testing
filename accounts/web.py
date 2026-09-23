"""Minimal HTML entry point for the teacher UI, using standard Django auth."""

from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST


@csrf_protect
@require_http_methods(["GET", "POST"])
def login_page(request):
    if request.method == "GET" and request.user.is_authenticated:
        if request.user.role == "TEACHER":
            return redirect("teacher:test-list")
        return render(request, "accounts/signed_in.html")
    form = AuthenticationForm(request, data=request.POST if request.method == "POST" else None)
    form.fields["username"].label = "Имя пользователя"
    form.fields["password"].label = "Пароль"
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("teacher:test-list" if request.user.role == "TEACHER" else "login")
    return render(request, "accounts/login.html", {"form": form}, status=401 if form.is_bound else 200)


@csrf_protect
@require_POST
def logout_page(request):
    logout(request)
    return redirect("login")
