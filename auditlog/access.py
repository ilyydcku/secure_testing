"""Read scope for the future administrative audit view."""

from accounts.permissions import check_role
from auditlog.models import AuditEvent


def admin_events(user):
    check_role(user, "ADMIN")
    return AuditEvent.objects.all()
