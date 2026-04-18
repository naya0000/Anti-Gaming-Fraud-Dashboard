from django.urls import path

from . import views

urlpatterns = [
    path('', views.risk_inbox, name='risk_inbox'),
    path('flag/<int:flag_id>/', views.forensic_timeline, name='forensic_timeline'),
    path('rules/', views.rules_list, name='rules_list'),
    path('audit/', views.audit_log, name='audit_log'),
]
