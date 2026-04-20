from django.conf import settings


def immutable_audit_log_enabled() -> bool:
    return getattr(settings, 'COMPLIANCE_IMMUTABLE_AUDIT_LOG', True)
