"""
Dynamic Rules Engine.

Instead of hardcoding thresholds, the engine walks every *active*
ComplianceRule row, looks at its `parameter_json`, and applies the
corresponding detector function. Adding a new rule = adding a row in the
DB (or a new detector key here), with no redeploy of thresholds.

Spec reference (Project 6, "Dynamic Rules Engine"):
  * Rule 1 (Speeding):         completion time < X% of module's company average
  * Rule 2 (Pattern Guessing): quiz finished in < N seconds at 0% score
  * Rule 3 (Distraction):      tab switches > N during a 7-minute sprint
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from .models import (
    ComplianceAuditLog,
    ComplianceRule,
    FlaggedSession,
    TrainingSession,
)


# Each detector returns (did_violate: bool, evidence: dict).
Detector = Callable[[TrainingSession, dict], Tuple[bool, dict]]


# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #

def _speeding(session: TrainingSession, params: dict) -> Tuple[bool, dict]:
    """Rule 1 - Impossibly fast completion."""
    ratio_threshold = float(params.get('speed_ratio_threshold', 0.2))
    company_avg = max(session.module.company_avg_seconds, 1)
    actual_ratio = session.total_time_seconds / company_avg
    violated = actual_ratio < ratio_threshold
    return violated, {
        'actual_time_seconds': session.total_time_seconds,
        'company_avg_seconds': company_avg,
        'ratio': round(actual_ratio, 3),
        'threshold_ratio': ratio_threshold,
    }


def _pattern_guessing(session: TrainingSession, params: dict) -> Tuple[bool, dict]:
    """Rule 2 - Blind guessing to skip."""
    max_quiz_seconds = int(params.get('max_quiz_seconds', 5))
    max_score_percent = int(params.get('max_score_percent', 0))
    violated = (
        session.quiz_time_seconds <= max_quiz_seconds
        and session.quiz_score_percent <= max_score_percent
    )
    return violated, {
        'quiz_time_seconds': session.quiz_time_seconds,
        'quiz_score_percent': session.quiz_score_percent,
        'max_allowed_quiz_seconds': max_quiz_seconds,
        'max_allowed_score_percent': max_score_percent,
    }


def _distraction(session: TrainingSession, params: dict) -> Tuple[bool, dict]:
    """Rule 3 - Too many tab switches during the sprint."""
    max_tab_switches = int(params.get('max_tab_switches', 5))
    violated = session.tab_switch_count > max_tab_switches
    return violated, {
        'tab_switch_count': session.tab_switch_count,
        'max_tab_switches_allowed': max_tab_switches,
        'sprint_duration_seconds': session.total_time_seconds,
    }


def _perfect_score_too_fast(session: TrainingSession, params: dict) -> Tuple[bool, dict]:
    """Optional bonus rule - flagged as 'Impossible Speed Verification' in spec example."""
    min_time_seconds = int(params.get('min_time_seconds', 30))
    requires_100 = bool(params.get('requires_100_score', True))
    violated = (
        session.total_time_seconds < min_time_seconds
        and ((not requires_100) or session.quiz_score_percent == 100)
    )
    return violated, {
        'actual_time_seconds': session.total_time_seconds,
        'quiz_score_percent': session.quiz_score_percent,
        'min_time_seconds': min_time_seconds,
        'requires_100_score': requires_100,
    }


# Each ComplianceRule row carries a `parameter_json["detector"]` key telling
# us which function to run. This is the only coupling between DB and code.
DETECTORS: Dict[str, Detector] = {
    'speeding': _speeding,
    'pattern_guessing': _pattern_guessing,
    'distraction': _distraction,
    'perfect_score_too_fast': _perfect_score_too_fast,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def evaluate_session(session: TrainingSession) -> list[FlaggedSession]:
    """
    Run every active rule against the given session. Create FlaggedSession
    records for any violations, apply the Automated Penalty System, and
    return the list of newly created flags.
    """
    created: list[FlaggedSession] = []
    for rule in ComplianceRule.objects.filter(is_active=True):
        detector_key = rule.parameter_json.get('detector')
        detector = DETECTORS.get(detector_key)
        if detector is None:
            continue
        violated, evidence = detector(session, rule.parameter_json)
        if not violated:
            continue
        flag, was_created = FlaggedSession.objects.get_or_create(
            session=session,
            rule_violated=rule,
            defaults={
                'agent': session.agent,
                'evidence': evidence,
                # Automated Penalty System: High severity auto-penalizes.
                'leaderboard_points_revoked': (rule.severity_level == 'High'),
                'streak_shield_locked': (rule.severity_level == 'High'),
            },
        )
        if was_created:
            created.append(flag)
    return created


def resolve_flag(
    flag: FlaggedSession,
    action: str,
    manager_name: str,
    notes: str,
) -> ComplianceAuditLog:
    """
    Apply a manager's resolution to a flag and write an immutable audit log.
    The flag itself is mutated (resolution_status), but the audit trail is
    append-only.
    """
    valid_actions = {a for a, _ in ComplianceAuditLog.ACTION_CHOICES}
    if action not in valid_actions:
        raise ValueError(f'Invalid action: {action}')

    flag.resolution_status = action
    # Un-lock streak shield if manager approved the session.
    if action == 'approved':
        flag.streak_shield_locked = False
        flag.leaderboard_points_revoked = False
    flag.save(update_fields=[
        'resolution_status',
        'streak_shield_locked',
        'leaderboard_points_revoked',
    ])

    return ComplianceAuditLog.objects.create(
        flag=flag,
        manager_name=manager_name or 'Compliance Officer',
        action_taken=action,
        manager_justification_notes=notes or '',
    )


def inbox_stats() -> dict:
    """Summary counters shown on the Risk Inbox header."""
    qs = FlaggedSession.objects.filter(resolution_status='pending')
    return {
        'total_pending': qs.count(),
        'high': qs.filter(rule_violated__severity_level='High').count(),
        'medium': qs.filter(rule_violated__severity_level='Med').count(),
        'low': qs.filter(rule_violated__severity_level='Low').count(),
        'total_resolved': FlaggedSession.objects.exclude(
            resolution_status='pending'
        ).count(),
    }
