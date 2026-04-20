from django.test import TestCase
from django.urls import reverse

from compliance.models import ComplianceAuditLog, TelemetryEvent

from .common import ComplianceTestDataMixin


class ViewTests(ComplianceTestDataMixin, TestCase):
    def test_risk_inbox_filters_by_severity_and_status(self):
        high_rule = self.make_rule(
            rule_name='High Rule',
            severity_level='High',
            parameter_json={'detector': 'speeding'},
        )
        low_rule = self.make_rule(
            rule_name='Low Rule',
            severity_level='Low',
            parameter_json={'detector': 'distraction'},
        )
        pending_high = self.make_flag(rule_violated=high_rule)
        self.make_flag(rule_violated=high_rule, resolution_status='approved')
        self.make_flag(rule_violated=low_rule)

        response = self.client.get(reverse('risk_inbox'), {
            'severity': 'High',
            'status': 'pending',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['flags']), [pending_high])

    def test_forensic_timeline_loads(self):
        flag = self.make_flag()
        TelemetryEvent.objects.create(
            session=flag.session,
            offset_seconds=0,
            event_type='start',
            detail='Session started',
        )

        response = self.client.get(reverse('forensic_timeline', args=[flag.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['flag'], flag)
        self.assertContains(response, 'Forensic Timeline')

    def test_forensic_timeline_rejects_short_justification(self):
        flag = self.make_flag()

        response = self.client.post(
            reverse('forensic_timeline', args=[flag.id]),
            data={
                'action_taken': 'approved',
                'manager_id': 'angela.wang',
                'manager_justification_notes': 'too short',
            },
        )
        flag.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(flag.resolution_status, 'pending')
        self.assertEqual(ComplianceAuditLog.objects.count(), 0)
        self.assertTrue(
            response.context['form'].has_error('manager_justification_notes')
        )

    def test_forensic_timeline_valid_resolution_writes_audit_log_and_redirects(self):
        flag = self.make_flag()

        response = self.client.post(
            reverse('forensic_timeline', args=[flag.id]),
            data={
                'action_taken': 'approved',
                'manager_id': 'angela.wang',
                'manager_justification_notes': 'This session was manually verified as legitimate.',
            },
        )
        flag.refresh_from_db()
        audit_log = ComplianceAuditLog.objects.get(flag=flag)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse('forensic_timeline', args=[flag.id]))
        self.assertEqual(flag.resolution_status, 'approved')
        self.assertEqual(audit_log.manager_id, 'angela.wang')
        self.assertEqual(audit_log.action_taken, 'approved')
