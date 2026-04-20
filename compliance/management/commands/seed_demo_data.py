"""
Seed realistic mock data for the Anti-Gaming Fraud Dashboard.

Produces:
  * ~20 agents across 3 branches
  * 6 training modules (mix of topics FSC / AML / ILP / etc.)
  * ~80 training sessions (mix of clean + rule-violating patterns)
  * Telemetry events for each session so the Forensic Timeline has content
  * 3 compliance rules (all from spec)
  * Runs the rules engine over every session -> creates FlaggedSession rows
  * Adds a couple of already-resolved flags so the Audit Trail has content
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from compliance.models import (
    Agent,
    ComplianceAuditLog,
    ComplianceRule,
    FlaggedSession,
    TelemetryEvent,
    TrainingModule,
    TrainingSession,
)
from compliance.settings_utils import immutable_audit_log_enabled
from compliance.services import evaluate_session, resolve_flag


AGENT_NAMES = [
    ('A001', 'Wang Chia-hao',     '台北信義分行'),
    ('A002', 'Lin Mei-ling',      '台北信義分行'),
    ('A003', 'Chen Wei-ting',     '台北信義分行'),
    ('A004', 'Huang Shu-fen',     '台北信義分行'),
    ('A005', 'Lee Chih-yuan',     '台北信義分行'),
    ('A006', 'Wu Pei-jung',       '台北信義分行'),
    ('A007', 'Chang Yi-chun',     '台中勤美分行'),
    ('A008', 'Tsai Cheng-wei',    '台中勤美分行'),
    ('A009', 'Hsu Hui-min',       '台中勤美分行'),
    ('A010', 'Liu Tzu-hsuan',     '台中勤美分行'),
    ('A011', 'Kuo Ting-wei',      '台中勤美分行'),
    ('A012', 'Yang Chia-yu',      '台中勤美分行'),
    ('A013', 'Chou Cheng-te',     '高雄美術館分行'),
    ('A014', 'Hsieh Mei-hua',     '高雄美術館分行'),
    ('A015', 'Chiang Yu-hsiang',  '高雄美術館分行'),
    ('A016', 'Lo Chien-fu',       '高雄美術館分行'),
    ('A017', 'Teng Hsiao-ling',   '高雄美術館分行'),
    ('A018', 'Fang Jen-chieh',    '高雄美術館分行'),
    ('A019', 'Su Wan-chen',       '新竹竹科分行'),
    ('A020', 'Liao Kuan-yu',      '新竹竹科分行'),
]

MODULES = [
    ('AML Red Flags in Life Insurance Onboarding',
     'Anti-Money Laundering', 420, 380),
    ('Investment-Linked Product (ILP) Regulatory Constraints',
     'ILP Compliance', 420, 395),
    ('Cross-Selling Framework for Financial Products',
     'Cross-Sell', 420, 360),
    ('FSC 2026 Suitability Assessment Updates',
     'FSC Regulatory', 420, 405),
    ('Client Data Sharing Rules Under PIPA',
     'Data Privacy', 420, 350),
    ('Policy Churning Detection & Prevention',
     'Market Conduct', 420, 370),
]

RULES = [
    dict(
        rule_name='Impossible Speed (R1)',
        description='Completion time is less than 20% of the company average for that module.',
        severity_level='Med',
        parameter_json={'detector': 'speeding', 'speed_ratio_threshold': 0.2},
    ),
    dict(
        rule_name='Pattern Guessing (R2)',
        description='Agent finishes the quiz in under 5 seconds with 0% score (blind guessing).',
        severity_level='High',
        parameter_json={
            'detector': 'pattern_guessing',
            'max_quiz_seconds': 5,
            'max_score_percent': 0,
        },
    ),
    dict(
        rule_name='Distraction Overload (R3)',
        description='Agent switches browser tabs more than 5 times during a 7-minute sprint.',
        severity_level='Low',
        parameter_json={'detector': 'distraction', 'max_tab_switches': 5},
    ),
]


DISTRACTION_APPS = ['Line', 'Instagram', 'Facebook Messenger', 'YouTube', 'Gmail']


def _make_timeline_clean(session: TrainingSession):
    """Events for an honest learner."""
    events = []
    events.append(TelemetryEvent(session=session, offset_seconds=0,
                                  event_type='start', detail='Session started'))
    quiz_start = max(1, session.total_time_seconds - session.quiz_time_seconds)
    card_gap = max(1, (quiz_start - 10) // max(session.module.card_count, 1))
    cursor = 10
    for i in range(session.module.card_count):
        view_offset = min(cursor, max(quiz_start - 2, 1))
        events.append(TelemetryEvent(session=session, offset_seconds=view_offset,
                                      event_type='card_view',
                                      detail=f'Card {i+1}/{session.module.card_count}'))
        cursor = view_offset + max(card_gap - 5, 1)
        swipe_offset = min(cursor, max(quiz_start - 1, 1))
        events.append(TelemetryEvent(session=session, offset_seconds=swipe_offset,
                                      event_type='card_swipe',
                                      detail=f'Swiped card {i+1}'))
        cursor = swipe_offset + 5
    events.append(TelemetryEvent(session=session, offset_seconds=quiz_start,
                                  event_type='quiz_start'))
    for q in range(session.module.quiz_question_count):
        events.append(TelemetryEvent(
            session=session,
            offset_seconds=quiz_start + (session.quiz_time_seconds // (session.module.quiz_question_count + 1)) * (q + 1),
            event_type='quiz_answer',
            detail=f'Q{q+1} answered',
        ))
    events.append(TelemetryEvent(session=session, offset_seconds=session.total_time_seconds - 1,
                                  event_type='quiz_submit',
                                  detail=f'Score: {session.quiz_score_percent}%'))
    events.append(TelemetryEvent(session=session, offset_seconds=session.total_time_seconds,
                                  event_type='complete'))
    return events


def _make_timeline_speeding(session: TrainingSession):
    """Agent speed-clicks through."""
    events = [TelemetryEvent(session=session, offset_seconds=0,
                              event_type='start', detail='Session started')]
    # Swipe through all cards in first few seconds
    for i in range(session.module.card_count):
        events.append(TelemetryEvent(session=session, offset_seconds=1 + i,
                                      event_type='card_swipe',
                                      detail=f'Rapid swipe card {i+1}'))
    quiz_start = session.total_time_seconds - session.quiz_time_seconds
    events.append(TelemetryEvent(session=session, offset_seconds=quiz_start,
                                  event_type='quiz_start'))
    for q in range(session.module.quiz_question_count):
        events.append(TelemetryEvent(session=session,
                                      offset_seconds=quiz_start + q,
                                      event_type='quiz_answer',
                                      detail=f'Q{q+1} blind answer'))
    events.append(TelemetryEvent(session=session, offset_seconds=session.total_time_seconds,
                                  event_type='quiz_submit',
                                  detail=f'Score: {session.quiz_score_percent}%'))
    events.append(TelemetryEvent(session=session, offset_seconds=session.total_time_seconds,
                                  event_type='complete'))
    return events


def _make_timeline_distraction(session: TrainingSession):
    events = [TelemetryEvent(session=session, offset_seconds=0,
                              event_type='start', detail='Session started')]
    session_end = session.total_time_seconds
    cursor = 5
    for i in range(session.tab_switch_count):
        app = random.choice(DISTRACTION_APPS)
        events.append(TelemetryEvent(session=session, offset_seconds=cursor,
                                      event_type='tab_switch_away',
                                      detail=f'Switched to {app}'))
        cursor += random.randint(4, 12)
        if cursor >= session_end:
            break
        events.append(TelemetryEvent(session=session, offset_seconds=cursor,
                                      event_type='tab_switch_back',
                                      detail='Returned to training'))
        cursor += random.randint(20, 60)
        if cursor >= session_end:
            break
    quiz_start = min(session_end, max(cursor, session_end - session.quiz_time_seconds))
    events.append(TelemetryEvent(session=session, offset_seconds=quiz_start,
                                  event_type='quiz_start'))
    events.append(TelemetryEvent(session=session, offset_seconds=session_end,
                                  event_type='quiz_submit',
                                  detail=f'Score: {session.quiz_score_percent}%'))
    events.append(TelemetryEvent(session=session, offset_seconds=session_end,
                                  event_type='complete'))
    return events


def _make_timeline_guessing(session: TrainingSession):
    events = [TelemetryEvent(session=session, offset_seconds=0,
                              event_type='start', detail='Session started')]
    for i in range(session.module.card_count):
        events.append(TelemetryEvent(session=session, offset_seconds=1,
                                      event_type='card_swipe',
                                      detail=f'Instant swipe card {i+1}'))
    events.append(TelemetryEvent(session=session,
                                  offset_seconds=session.total_time_seconds - session.quiz_time_seconds,
                                  event_type='quiz_start'))
    for q in range(session.module.quiz_question_count):
        events.append(TelemetryEvent(
            session=session,
            offset_seconds=session.total_time_seconds - session.quiz_time_seconds + 1,
            event_type='quiz_answer',
            detail=f'Q{q+1} random guess',
        ))
    events.append(TelemetryEvent(session=session, offset_seconds=session.total_time_seconds,
                                  event_type='quiz_submit',
                                  detail=f'Score: {session.quiz_score_percent}% (blind)'))
    events.append(TelemetryEvent(session=session, offset_seconds=session.total_time_seconds,
                                  event_type='complete'))
    return events


class Command(BaseCommand):
    help = 'Seed mock agents, modules, sessions, rules, and flagged sessions.'

    def add_arguments(self, parser):
        parser.add_argument('--fresh', action='store_true',
                            help='Wipe existing demo data before seeding.')

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['fresh']:
            if immutable_audit_log_enabled() and ComplianceAuditLog.objects.exists():
                raise CommandError(
                    'Cannot wipe immutable audit logs. Use a new database path for a fresh demo dataset.'
                )
            self.stdout.write('Wiping existing demo data...')
            if not immutable_audit_log_enabled():
                ComplianceAuditLog.objects.all().delete()
            FlaggedSession.objects.all().delete()
            TelemetryEvent.objects.all().delete()
            TrainingSession.objects.all().delete()
            ComplianceRule.objects.all().delete()
            TrainingModule.objects.all().delete()
            Agent.objects.all().delete()

        if Agent.objects.exists():
            self.stdout.write(self.style.WARNING(
                'Data already present. Use --fresh to reseed.'))
            return

        random.seed(42)

        # --- Agents ---
        agents = []
        for code, name, branch in AGENT_NAMES:
            agents.append(Agent.objects.create(
                agent_code=code, full_name=name, branch=branch,
                role='Life Insurance Agent'))
        self.stdout.write(f'  + {len(agents)} agents')

        # --- Modules ---
        modules = []
        for title, topic, expected, avg in MODULES:
            modules.append(TrainingModule.objects.create(
                title=title, topic=topic,
                expected_duration_seconds=expected,
                company_avg_seconds=avg))
        self.stdout.write(f'  + {len(modules)} training modules')

        # --- Rules ---
        for r in RULES:
            ComplianceRule.objects.create(**r)
        self.stdout.write(f'  + {len(RULES)} compliance rules')

        # --- Training Sessions ---
        # Distribution: ~60% clean, ~15% speeding, ~13% guessing,
        # ~13% distraction.
        now = timezone.now()
        created_sessions = 0
        flags_created_total = 0

        profiles = (
            ['clean'] * 40 +
            ['speeding'] * 12 +
            ['guessing'] * 13 +
            ['distraction'] * 13
        )
        random.shuffle(profiles)

        for i, profile in enumerate(profiles):
            agent = random.choice(agents)
            module = random.choice(modules)
            started_at = now - timedelta(
                days=random.randint(0, 14),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )

            if profile == 'clean':
                total = random.randint(
                    int(module.company_avg_seconds * 0.7),
                    int(module.company_avg_seconds * 1.2),
                )
                quiz_time = random.randint(30, 80)
                score = random.choice([67, 67, 100, 100, 100, 100, 33])
                tabs = random.randint(0, 2)
                timeline_fn = _make_timeline_clean
            elif profile == 'speeding':
                total = random.randint(15, int(module.company_avg_seconds * 0.18))
                quiz_time = random.randint(2, 8)
                score = random.choice([0, 33, 67, 100])
                tabs = random.randint(0, 1)
                timeline_fn = _make_timeline_speeding
            elif profile == 'guessing':
                total = random.randint(40, 120)
                quiz_time = random.randint(1, 4)
                score = 0
                tabs = random.randint(0, 2)
                timeline_fn = _make_timeline_guessing
            elif profile == 'distraction':
                total = random.randint(400, 700)
                quiz_time = random.randint(40, 90)
                score = random.choice([67, 100, 33])
                tabs = random.randint(6, 12)
                timeline_fn = _make_timeline_distraction
            else:
                continue

            session = TrainingSession.objects.create(
                agent=agent,
                module=module,
                started_at=started_at,
                completed_at=started_at + timedelta(seconds=total),
                total_time_seconds=total,
                quiz_score_percent=score,
                quiz_time_seconds=quiz_time,
                tab_switch_count=tabs,
                status='completed',
            )
            TelemetryEvent.objects.bulk_create(timeline_fn(session))
            created_sessions += 1

            new_flags = evaluate_session(session)
            flags_created_total += len(new_flags)

        self.stdout.write(f'  + {created_sessions} training sessions')
        self.stdout.write(
            f'  + {flags_created_total} flags raised by rules engine')

        # --- Sample resolutions for audit trail ---
        sample_flags = list(FlaggedSession.objects.all()[:3])
        if sample_flags:
            resolve_flag(
                sample_flags[0],
                action='voided',
                manager_id='angela.wang',
                notes='Session time impossible given module content. Retake required.',
            )
            if len(sample_flags) > 1:
                resolve_flag(
                    sample_flags[1],
                    action='escalated',
                    manager_id='david.chen',
                    notes='Repeated R2 pattern across multiple modules. HR review needed.',
                )
            if len(sample_flags) > 2:
                resolve_flag(
                    sample_flags[2],
                    action='approved',
                    manager_id='angela.wang',
                    notes='Agent on known fast-reading profile; session verified legitimate.',
                )
            self.stdout.write('  + 3 sample audit-log entries')

        self.stdout.write(self.style.SUCCESS(
            '\nSeed complete. Run: python manage.py runserver 0.0.0.0:8000'))
