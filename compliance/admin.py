from django.contrib import admin

from .models import (
    Agent,
    ComplianceAuditLog,
    ComplianceRule,
    FlaggedSession,
    TelemetryEvent,
    TrainingModule,
    TrainingSession,
)
from .settings_utils import immutable_audit_log_enabled


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ('agent_code', 'full_name', 'branch', 'role', 'joined_on')
    search_fields = ('agent_code', 'full_name', 'branch')


@admin.register(TrainingModule)
class TrainingModuleAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'topic', 'expected_duration_seconds',
        'company_avg_seconds', 'card_count', 'quiz_question_count',
    )
    search_fields = ('title', 'topic')


class TelemetryEventInline(admin.TabularInline):
    model = TelemetryEvent
    extra = 0


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'agent', 'module', 'started_at',
        'total_time_seconds', 'quiz_score_percent',
        'tab_switch_count', 'status',
    )
    list_filter = ('status', 'module')
    search_fields = ('agent__agent_code', 'agent__full_name')
    inlines = [TelemetryEventInline]


@admin.register(ComplianceRule)
class ComplianceRuleAdmin(admin.ModelAdmin):
    list_display = ('rule_name', 'severity_level', 'is_active', 'created_at')
    list_filter = ('severity_level', 'is_active')


@admin.register(FlaggedSession)
class FlaggedSessionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'agent', 'rule_violated', 'resolution_status',
        'flag_timestamp', 'leaderboard_points_revoked', 'streak_shield_locked',
    )
    list_filter = ('resolution_status', 'rule_violated__severity_level')
    search_fields = ('agent__agent_code', 'agent__full_name')


@admin.register(ComplianceAuditLog)
class ComplianceAuditLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'flag', 'manager_id', 'action_taken', 'timestamp')
    list_filter = ('action_taken',)
    search_fields = ('manager_id',)
    readonly_fields = ('flag', 'manager_id', 'action_taken', 'manager_justification_notes', 'timestamp')

    def has_add_permission(self, request):
        return not immutable_audit_log_enabled()

    def has_change_permission(self, request, obj=None):
        if immutable_audit_log_enabled():
            return request.method in ('GET', 'HEAD', 'OPTIONS')
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if immutable_audit_log_enabled():
            return False
        return super().has_delete_permission(request, obj)
