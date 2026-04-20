from django.utils import timezone

from compliance.models import (
    Agent,
    ComplianceRule,
    FlaggedSession,
    TrainingModule,
    TrainingSession,
)


class ComplianceTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        cls.agent = Agent.objects.create(
            agent_code='A001',
            full_name='Test Agent',
            branch='Taipei',
        )
        cls.module = TrainingModule.objects.create(
            title='AML Basics',
            topic='AML',
            expected_duration_seconds=420,
            company_avg_seconds=400,
            card_count=5,
            quiz_question_count=3,
        )

    def make_session(self, **overrides):
        defaults = {
            'agent': self.agent,
            'module': self.module,
            'started_at': timezone.now(),
            'completed_at': timezone.now(),
            'total_time_seconds': 300,
            'quiz_score_percent': 100,
            'quiz_time_seconds': 60,
            'tab_switch_count': 0,
            'status': 'completed',
        }
        defaults.update(overrides)
        return TrainingSession.objects.create(**defaults)

    def make_rule(self, **overrides):
        defaults = {
            'rule_name': f'Rule {ComplianceRule.objects.count() + 1}',
            'severity_level': 'High',
            'parameter_json': {},
            'is_active': True,
        }
        defaults.update(overrides)
        return ComplianceRule.objects.create(**defaults)

    def make_flag(self, **overrides):
        session = overrides.pop('session', None) or self.make_session()
        rule = overrides.pop('rule_violated', None) or self.make_rule(
            rule_name=f'Flag Rule {FlaggedSession.objects.count() + 1}',
        )
        defaults = {
            'session': session,
            'agent': session.agent,
            'rule_violated': rule,
            'resolution_status': 'pending',
            'evidence': {'sample': True},
            'leaderboard_points_revoked': rule.severity_level == 'High',
            'streak_shield_locked': rule.severity_level == 'High',
        }
        defaults.update(overrides)
        return FlaggedSession.objects.create(**defaults)

