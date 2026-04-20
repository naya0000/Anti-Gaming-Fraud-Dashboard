from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ResolveFlagForm
from .models import (
    ComplianceAuditLog,
    ComplianceRule,
    FlaggedSession,
)
from .services import inbox_stats, resolve_flag


# --------------------------------------------------------------------------- #
# Risk Inbox
# --------------------------------------------------------------------------- #

def risk_inbox(request):
    """
    The high-priority dashboard for Branch Managers / Compliance Officers.
    Looks like a cybersecurity threat monitor: rows grouped by Severity.
    """
    severity_filter = request.GET.get('severity', 'all')
    status_filter = request.GET.get('status', 'pending')

    flags = (
        FlaggedSession.objects
        .select_related('agent', 'session', 'session__module', 'rule_violated')
    )

    if status_filter != 'all':
        flags = flags.filter(resolution_status=status_filter)
    if severity_filter != 'all':
        flags = flags.filter(rule_violated__severity_level=severity_filter)

    # Order by severity (High -> Med -> Low) then recency
    severity_order = {'High': 0, 'Med': 1, 'Low': 2}
    flags_list = sorted(
        flags,
        key=lambda f: (severity_order.get(f.severity, 99), -int(f.flag_timestamp.timestamp())),
    )

    ctx = {
        'flags': flags_list,
        'stats': inbox_stats(),
        'severity_filter': severity_filter,
        'status_filter': status_filter,
    }
    return render(request, 'compliance/risk_inbox.html', ctx)


# --------------------------------------------------------------------------- #
# Forensic Timeline
# --------------------------------------------------------------------------- #

def forensic_timeline(request, flag_id: int):
    """
    Drill-down: visually map the agent's exact actions on a timeline.
    Also handles form POST from the Resolution Action Bar.
    """
    flag = get_object_or_404(
        FlaggedSession.objects.select_related(
            'agent', 'session', 'session__module', 'rule_violated',
        ),
        pk=flag_id,
    )
    events = flag.session.events.all()

    if request.method == 'POST':
        if flag.resolution_status != 'pending':
            messages.warning(request, 'This flag has already been resolved.')
            return redirect('forensic_timeline', flag_id=flag.id)

        form = ResolveFlagForm(request.POST)
        if form.is_valid():
            resolve_flag(
                flag,
                action=form.cleaned_data['action_taken'],
                manager_id=form.cleaned_data['manager_id'],
                notes=form.cleaned_data['manager_justification_notes'],
            )
            messages.success(
                request,
                f'Flag #{flag.id} resolved ({form.cleaned_data["action_taken"]}) and audit log written.',
            )
            return redirect('forensic_timeline', flag_id=flag.id)
    else:
        form = ResolveFlagForm()

    # Pre-compute timeline length for the visual axis
    max_offset = max(
        (e.offset_seconds for e in events),
        default=flag.session.total_time_seconds or 1,
    )
    total_span = max(max_offset, flag.session.total_time_seconds or 1, 1)

    event_rows = []
    for e in events:
        event_rows.append({
            'event': e,
            'percent': round(100 * e.offset_seconds / total_span, 2),
        })

    related_flags = (
        flag.session.flags
        .select_related('rule_violated')
        .exclude(id=flag.id)
    )

    ctx = {
        'flag': flag,
        'event_rows': event_rows,
        'total_span': total_span,
        'form': form,
        'related_flags': related_flags,
        'audit_logs': flag.audit_logs.all(),
    }
    return render(request, 'compliance/forensic_timeline.html', ctx)


# --------------------------------------------------------------------------- #
# Rules & Audit log pages
# --------------------------------------------------------------------------- #

def rules_list(request):
    """Admin-style view of the Logic Dictionary."""
    rules = ComplianceRule.objects.annotate(
        total_flags=Count('flags'),
        pending_flags=Count('flags', filter=Q(flags__resolution_status='pending')),
    )
    return render(request, 'compliance/rules_list.html', {'rules': rules})


def audit_log(request):
    """FSC-style immutable audit trail."""
    logs = (
        ComplianceAuditLog.objects
        .select_related('flag', 'flag__agent', 'flag__rule_violated')
    )
    return render(request, 'compliance/audit_log.html', {'logs': logs})
