"""
Compliance domain models.

Maps directly onto the "Database Design" section of Project 6:

  * ComplianceRule       -> The Logic Dictionary
  * FlaggedSession       -> The Inbox Queue
  * ComplianceAuditLog   -> The Immutable Record

Plus supporting models that give us the telemetry the rules engine needs
(Agent, TrainingModule, TrainingSession, TelemetryEvent). These are the
"P2/P3 data" referenced by the spec's session_id foreign key.
"""
from django.core.exceptions import ValidationError
from django.db import models

from .settings_utils import immutable_audit_log_enabled


# --------------------------------------------------------------------------- #
# Supporting models (the telemetry data source)
# --------------------------------------------------------------------------- #

class Agent(models.Model):
    """A life insurance / financial services agent who must take training."""
    agent_code = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=100)
    branch = models.CharField(max_length=50)
    role = models.CharField(max_length=50, default='Life Insurance Agent')
    joined_on = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.agent_code} - {self.full_name}"


class TrainingModule(models.Model):
    """A 7-minute micro-learning module (flashcards + quiz)."""
    title = models.CharField(max_length=200)
    topic = models.CharField(max_length=100)
    expected_duration_seconds = models.IntegerField(
        default=420,
        help_text="Target reading time (seconds). Default 7min = 420s.",
    )
    company_avg_seconds = models.IntegerField(
        default=380,
        help_text="Rolling company-wide average completion time.",
    )
    card_count = models.IntegerField(default=5)
    quiz_question_count = models.IntegerField(default=3)

    def __str__(self):
        return self.title


class TrainingSession(models.Model):
    """
    One completion attempt by an agent on a module.
    This is the `session_id` referenced by FlaggedSession.session in the spec.
    """
    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
    ]
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='sessions')
    module = models.ForeignKey(TrainingModule, on_delete=models.CASCADE, related_name='sessions')
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    total_time_seconds = models.IntegerField()
    quiz_score_percent = models.IntegerField(default=0)
    quiz_time_seconds = models.IntegerField(default=0)
    tab_switch_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Session #{self.id} - {self.agent.agent_code} / {self.module.title}"


class TelemetryEvent(models.Model):
    """
    Fine-grained events that feed the Forensic Timeline drill-down view.
    Example: 0:00 Started -> 0:03 Switched to Line app -> 0:05 Returned...
    """
    EVENT_TYPES = [
        ('start', 'Session Start'),
        ('tab_switch_away', 'Switched To External App'),
        ('tab_switch_back', 'Returned To Training'),
        ('card_view', 'Flashcard Viewed'),
        ('card_swipe', 'Flashcard Swiped'),
        ('quiz_start', 'Quiz Started'),
        ('quiz_answer', 'Quiz Answered'),
        ('quiz_submit', 'Quiz Submitted'),
        ('complete', 'Session Complete'),
    ]
    session = models.ForeignKey(
        TrainingSession,
        on_delete=models.CASCADE,
        related_name='events',
    )
    offset_seconds = models.IntegerField(help_text='Seconds from session start')
    event_type = models.CharField(max_length=32, choices=EVENT_TYPES)
    detail = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['offset_seconds', 'id']

    @property
    def offset_label(self):
        m, s = divmod(self.offset_seconds, 60)
        return f"{m}:{s:02d}"

    def __str__(self):
        return f"{self.offset_label} {self.get_event_type_display()}"


# --------------------------------------------------------------------------- #
# Core spec models
# --------------------------------------------------------------------------- #

class ComplianceRule(models.Model):
    """
    Spec: ComplianceRules (The Logic Dictionary)

    parameter_json holds a configurable threshold bag instead of hardcoding
    them in code. The rules engine (services.py) reads this bag at runtime.
    """
    SEVERITY_CHOICES = [
        ('Low', 'Low'),
        ('Med', 'Medium'),
        ('High', 'High'),
    ]
    rule_name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    parameter_json = models.JSONField(
        default=dict,
        help_text='e.g. {"speed_ratio_threshold": 0.2} - read by rules engine',
    )
    severity_level = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-severity_level', 'rule_name']

    def __str__(self):
        return f"[{self.severity_level}] {self.rule_name}"


class FlaggedSession(models.Model):
    """
    Spec: FlaggedSessions (The Inbox Queue)

    One row per (session, rule_violated) hit. A single session may trip
    multiple rules; each violation is its own flag in the inbox.
    """
    RESOLUTION_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved (False Alarm)'),
        ('voided', 'Voided & Retake Required'),
        ('escalated', 'Escalated to HR'),
    ]
    session = models.ForeignKey(
        TrainingSession,
        on_delete=models.CASCADE,
        related_name='flags',
    )
    agent = models.ForeignKey(
        Agent,
        on_delete=models.CASCADE,
        related_name='flags',
    )
    rule_violated = models.ForeignKey(
        ComplianceRule,
        on_delete=models.PROTECT,
        related_name='flags',
    )
    flag_timestamp = models.DateTimeField(auto_now_add=True)
    resolution_status = models.CharField(
        max_length=20,
        choices=RESOLUTION_CHOICES,
        default='pending',
    )
    evidence = models.JSONField(
        default=dict,
        help_text='Captured values the rules engine compared against thresholds',
    )
    # Automated Penalty System fields (spec):
    leaderboard_points_revoked = models.BooleanField(default=False)
    streak_shield_locked = models.BooleanField(default=False)

    class Meta:
        ordering = ['-flag_timestamp']
        indexes = [
            models.Index(fields=['resolution_status']),
            models.Index(fields=['-flag_timestamp']),
        ]
        unique_together = [('session', 'rule_violated')]

    def __str__(self):
        return f"Flag #{self.id} - {self.rule_violated.rule_name}"

    @property
    def severity(self):
        return self.rule_violated.severity_level

    @property
    def severity_css(self):
        return {
            'High': 'danger',
            'Med': 'warning',
            'Low': 'info',
        }.get(self.severity, 'secondary')


class ComplianceAuditLog(models.Model):
    """
    Spec: ComplianceAuditLog (The Immutable Record)

    Append-only trail of every manager action for FSC audit purposes.
    We do not expose UPDATE / DELETE views on this table.
    """
    ACTION_CHOICES = [
        ('approved', 'Approve (False Alarm)'),
        ('voided', 'Void Session & Require Retake'),
        ('escalated', 'Escalate to HR'),
    ]
    flag = models.ForeignKey(
        FlaggedSession,
        on_delete=models.PROTECT,
        related_name='audit_logs',
    )
    manager_id = models.CharField(max_length=100, default='compliance.officer')
    action_taken = models.CharField(max_length=20, choices=ACTION_CHOICES)
    manager_justification_notes = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        if (
            immutable_audit_log_enabled()
            and self.pk
            and ComplianceAuditLog.objects.filter(pk=self.pk).exists()
        ):
            raise ValidationError('Compliance audit logs are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if immutable_audit_log_enabled():
            raise ValidationError('Compliance audit logs cannot be deleted.')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Audit #{self.id} - {self.action_taken} by {self.manager_id}"
