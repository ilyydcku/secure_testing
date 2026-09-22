from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    occurred_at = models.DateTimeField()
    category = models.CharField(max_length=50)
    event_type = models.CharField(max_length=100)
    outcome = models.CharField(max_length=50, null=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
    )
    actor_role = models.CharField(max_length=20, null=True)
    target_type = models.CharField(max_length=100, null=True)
    target_id = models.BigIntegerField(null=True)
    source_ip = models.GenericIPAddressField(null=True)
    user_agent = models.TextField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(actor_role__isnull=True)
                    | models.Q(actor_role__in=["STUDENT", "TEACHER", "ADMIN"])
                ),
                name="auditlog_auditevent_actor_role_valid",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(target_type__isnull=True)
                        & models.Q(target_id__isnull=True)
                    )
                    | (
                        models.Q(target_type__isnull=False)
                        & models.Q(target_id__isnull=False)
                    )
                ),
                name="auditlog_auditevent_target_pair",
            ),
        ]
