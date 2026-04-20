from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import ComplianceAuditLog, TrainingSession
from .settings_utils import immutable_audit_log_enabled
from .services import evaluate_session


@receiver(post_save, sender=TrainingSession)
def evaluate_training_session_on_create(sender, instance, created, **kwargs):
    if created:
        evaluate_session(instance)


@receiver(pre_delete, sender=ComplianceAuditLog)
def prevent_audit_log_deletion(sender, instance, **kwargs):
    if immutable_audit_log_enabled():
        raise ValidationError('Compliance audit logs cannot be deleted.')
