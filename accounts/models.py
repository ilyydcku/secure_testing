from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    role = models.CharField(max_length=20)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["STUDENT", "TEACHER", "ADMIN"]),
                name="accounts_user_role_valid",
            ),
        ]
