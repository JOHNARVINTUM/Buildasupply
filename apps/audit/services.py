from .models import AuditLog
def log_action(*, actor, action, target, before=None, after=None):
    return AuditLog.objects.create(actor=actor, action=action, target_type=target._meta.label, target_id=target.pk, before=before or {}, after=after or {})
