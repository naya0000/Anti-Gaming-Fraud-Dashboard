from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from compliance.models import ComplianceAuditLog, FlaggedSession
from compliance.services import evaluate_session, resolve_flag

from .common import ComplianceTestDataMixin


class RulesEngineTests(ComplianceTestDataMixin, TestCase):
    def setUp(self):
        self.evaluate_session_patcher = patch('compliance.signals.evaluate_session')
        self.mock_evaluate_session = self.evaluate_session_patcher.start()
        self.addCleanup(self.evaluate_session_patcher.stop)

    def test_speeding_rule_triggers_with_expected_evidence(self):
        rule = self.make_rule(
            rule_name='Impossible Speed',
            parameter_json={'detector': 'speeding', 'speed_ratio_threshold': 0.2},
        )
        session = self.make_session(total_time_seconds=50)

        created = evaluate_session(session)

        self.assertEqual(len(created), 1)
        flag = created[0]
        self.assertEqual(flag.rule_violated, rule)
        self.assertEqual(flag.evidence, {
            'actual_time_seconds': 50,
            'company_avg_seconds': 400,
            'ratio': 0.125,
            'threshold_ratio': 0.2,
        })
        self.assertTrue(flag.leaderboard_points_revoked)
        self.assertTrue(flag.streak_shield_locked)

    def test_speeding_rule_does_not_trigger_above_threshold(self):
        self.make_rule(
            rule_name='Impossible Speed',
            parameter_json={'detector': 'speeding', 'speed_ratio_threshold': 0.2},
        )
        session = self.make_session(total_time_seconds=120)

        created = evaluate_session(session)

        self.assertEqual(created, [])

    def test_training_session_creation_automatically_scans_active_rules(self):
        self.evaluate_session_patcher.stop()
        self.make_rule(
            rule_name='Impossible Speed',
            parameter_json={'detector': 'speeding', 'speed_ratio_threshold': 0.2},
        )

        session = self.make_session(total_time_seconds=50)

        flag = FlaggedSession.objects.get(session=session)
        self.assertEqual(flag.rule_violated.rule_name, 'Impossible Speed')
        self.assertEqual(FlaggedSession.objects.count(), 1)

    def test_high_risk_session_creation_applies_automatic_penalties(self):
        self.evaluate_session_patcher.stop()
        self.make_rule(
            rule_name='Pattern Guessing',
            severity_level='High',
            parameter_json={
                'detector': 'pattern_guessing',
                'max_quiz_seconds': 5,
                'max_score_percent': 0,
            },
        )

        session = self.make_session(quiz_time_seconds=4, quiz_score_percent=0)

        flag = FlaggedSession.objects.get(session=session)
        self.assertTrue(flag.leaderboard_points_revoked)
        self.assertTrue(flag.streak_shield_locked)

    def test_pattern_guessing_rule_triggers_with_expected_evidence(self):
        rule = self.make_rule(
            rule_name='Pattern Guessing',
            parameter_json={
                'detector': 'pattern_guessing',
                'max_quiz_seconds': 5,
                'max_score_percent': 0,
            },
        )
        session = self.make_session(quiz_time_seconds=4, quiz_score_percent=0)

        created = evaluate_session(session)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].rule_violated, rule)
        self.assertEqual(created[0].evidence, {
            'quiz_time_seconds': 4,
            'quiz_score_percent': 0,
            'max_allowed_quiz_seconds': 5,
            'max_allowed_score_percent': 0,
        })

    def test_pattern_guessing_rule_does_not_trigger_with_higher_score(self):
        self.make_rule(
            rule_name='Pattern Guessing',
            parameter_json={
                'detector': 'pattern_guessing',
                'max_quiz_seconds': 5,
                'max_score_percent': 0,
            },
        )
        session = self.make_session(quiz_time_seconds=4, quiz_score_percent=33)

        created = evaluate_session(session)

        self.assertEqual(created, [])

    def test_distraction_rule_triggers_with_expected_evidence(self):
        rule = self.make_rule(
            rule_name='Distraction Overload',
            severity_level='Low',
            parameter_json={'detector': 'distraction', 'max_tab_switches': 5},
        )
        session = self.make_session(total_time_seconds=500, tab_switch_count=7)

        created = evaluate_session(session)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].rule_violated, rule)
        self.assertEqual(created[0].evidence, {
            'tab_switch_count': 7,
            'max_tab_switches_allowed': 5,
            'sprint_duration_seconds': 500,
        })
        self.assertFalse(created[0].leaderboard_points_revoked)
        self.assertFalse(created[0].streak_shield_locked)

    def test_distraction_rule_does_not_trigger_at_threshold(self):
        self.make_rule(
            rule_name='Distraction Overload',
            severity_level='Low',
            parameter_json={'detector': 'distraction', 'max_tab_switches': 5},
        )
        session = self.make_session(tab_switch_count=5)

        created = evaluate_session(session)

        self.assertEqual(created, [])

class ResolveFlagServiceTests(ComplianceTestDataMixin, TestCase):
    def test_resolve_flag_creates_audit_log_and_unlocks_approved_flag(self):
        rule = self.make_rule(
            rule_name='Impossible Speed',
            parameter_json={'detector': 'speeding', 'speed_ratio_threshold': 0.2},
        )
        flag = self.make_flag(rule_violated=rule)

        audit_log = resolve_flag(
            flag,
            action='approved',
            manager_id='angela.wang',
            notes='This session was reviewed manually.',
        )
        flag.refresh_from_db()

        self.assertEqual(flag.resolution_status, 'approved')
        self.assertFalse(flag.streak_shield_locked)
        self.assertFalse(flag.leaderboard_points_revoked)
        self.assertEqual(audit_log.flag, flag)
        self.assertEqual(audit_log.manager_id, 'angela.wang')
        self.assertEqual(ComplianceAuditLog.objects.count(), 1)

    def test_resolve_flag_rejects_already_resolved_flag(self):
        flag = self.make_flag(resolution_status='voided')

        with self.assertRaisesMessage(ValueError, 'Flag has already been resolved.'):
            resolve_flag(
                flag,
                action='approved',
                manager_id='angela.wang',
                notes='This should not be allowed.',
            )

        self.assertEqual(ComplianceAuditLog.objects.count(), 0)

    def test_audit_log_cannot_be_updated_or_deleted(self):
        flag = self.make_flag()
        audit_log = resolve_flag(
            flag,
            action='voided',
            manager_id='angela.wang',
            notes='This session requires a retake.',
        )

        audit_log.action_taken = 'approved'
        with self.assertRaisesMessage(ValidationError, 'Compliance audit logs are immutable.'):
            audit_log.save()

        with self.assertRaisesMessage(ValidationError, 'Compliance audit logs cannot be deleted.'):
            ComplianceAuditLog.objects.filter(pk=audit_log.pk).delete()

    @override_settings(COMPLIANCE_IMMUTABLE_AUDIT_LOG=False)
    def test_audit_log_can_be_updated_and_deleted_when_immutability_is_disabled(self):
        flag = self.make_flag()
        audit_log = resolve_flag(
            flag,
            action='voided',
            manager_id='angela.wang',
            notes='This session requires a retake.',
        )

        audit_log.action_taken = 'escalated'
        audit_log.save()
        audit_log.refresh_from_db()
        self.assertEqual(audit_log.action_taken, 'escalated')

        ComplianceAuditLog.objects.filter(pk=audit_log.pk).delete()
        self.assertFalse(ComplianceAuditLog.objects.filter(pk=audit_log.pk).exists())
