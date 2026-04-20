from unittest.mock import patch

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from compliance.management.commands.seed_demo_data import (
    _make_timeline_clean,
    _make_timeline_distraction,
)
from compliance.models import TrainingModule, TrainingSession
from compliance.tests.common import ComplianceTestDataMixin
from compliance.services import resolve_flag


class SeedDemoDataTests(SimpleTestCase):
    def test_clean_timeline_never_exceeds_session_length(self):
        session = TrainingSession(
            module=TrainingModule(card_count=5, quiz_question_count=3),
            total_time_seconds=266,
            quiz_time_seconds=45,
            quiz_score_percent=67,
        )

        events = _make_timeline_clean(session)

        offsets = [event.offset_seconds for event in events]
        self.assertEqual(offsets[-1], session.total_time_seconds)
        self.assertLessEqual(max(offsets), session.total_time_seconds)


class SeedDemoDataCommandTests(ComplianceTestDataMixin, TestCase):
    def test_seed_demo_data_fresh_is_rejected_when_audit_logs_exist(self):
        flag = self.make_flag()
        resolve_flag(
            flag,
            action='voided',
            manager_id='angela.wang',
            notes='This session already has an immutable audit trail.',
        )

        with self.assertRaisesMessage(
            CommandError,
            'Cannot wipe immutable audit logs. Use a new database path for a fresh demo dataset.',
        ):
            call_command('seed_demo_data', '--fresh', stdout=StringIO(), stderr=StringIO())

    @override_settings(COMPLIANCE_IMMUTABLE_AUDIT_LOG=False)
    def test_seed_demo_data_fresh_is_allowed_when_immutability_is_disabled(self):
        flag = self.make_flag()
        resolve_flag(
            flag,
            action='voided',
            manager_id='angela.wang',
            notes='This session already has an immutable audit trail.',
        )

        call_command('seed_demo_data', '--fresh', stdout=StringIO(), stderr=StringIO())

    def test_distraction_timeline_never_exceeds_session_length(self):
        session = TrainingSession(
            module=TrainingModule(quiz_question_count=3),
            total_time_seconds=120,
            quiz_time_seconds=30,
            quiz_score_percent=67,
            tab_switch_count=12,
        )

        with patch(
            'compliance.management.commands.seed_demo_data.random.randint',
            side_effect=[12, 60] * session.tab_switch_count,
        ), patch(
            'compliance.management.commands.seed_demo_data.random.choice',
            return_value='Line',
        ):
            events = _make_timeline_distraction(session)

        offsets = [event.offset_seconds for event in events]
        self.assertEqual(offsets[-1], session.total_time_seconds)
        self.assertLessEqual(max(offsets), session.total_time_seconds)
