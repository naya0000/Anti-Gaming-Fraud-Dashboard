from django.contrib import admin
from django.test import RequestFactory, TestCase

from compliance.admin import ComplianceAuditLogAdmin
from compliance.models import ComplianceAuditLog

from .common import ComplianceTestDataMixin


class AdminTests(ComplianceTestDataMixin, TestCase):
    def test_audit_log_admin_has_delete_permission_disabled(self):
        audit_log_admin = ComplianceAuditLogAdmin(ComplianceAuditLog, admin.site)
        request = RequestFactory().get('/admin/compliance/complianceauditlog/')

        self.assertFalse(audit_log_admin.has_delete_permission(request))

    def test_audit_log_admin_is_read_only(self):
        audit_log_admin = ComplianceAuditLogAdmin(ComplianceAuditLog, admin.site)
        get_request = RequestFactory().get('/admin/compliance/complianceauditlog/1/change/')
        post_request = RequestFactory().post('/admin/compliance/complianceauditlog/1/change/')

        self.assertTrue(audit_log_admin.has_change_permission(get_request))
        self.assertFalse(audit_log_admin.has_change_permission(post_request))
