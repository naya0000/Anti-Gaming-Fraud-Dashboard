# Anti-Gaming Fraud Dashboard & Compliance Auditor (Project 6)

A Django web console that helps a financial holding company detect agents who
"game" mandatory FSC compliance training — speed-clicking, blind-guessing on
quizzes, or browsing social apps while the clock ticks — and gives Branch
Managers / Compliance Officers a forensic view plus a resolution workflow
backed by an immutable audit trail.

This implements **Project 6: The "Anti-Gaming" Fraud Dashboard & Compliance
Auditor** from the project spec (see `docs/` in the original brief).

---

## Feature overview

| UI screen          | What it does                                                                                    |
|--------------------|-------------------------------------------------------------------------------------------------|
| **Risk Inbox**     | Cybersecurity-monitor style dashboard of flagged sessions, grouped by Severity (High/Med/Low). |
| **Forensic Timeline** | Drill-down view that visually maps the agent's telemetry events on a time axis.              |
| **Resolution Bar** | Manager clears a flag with Approve / Void & Retake / Escalate HR + justification notes.        |
| **Rules Engine**   | Rules and thresholds are DB-driven (`parameter_json`), no code redeploy needed to tune them.   |
| **Audit Trail**    | Append-only log of every manager action, ready for FSC audit queries.                          |

## Tech stack

- **Backend:** Python 3.10+ / Django 5.2
- **Frontend:** Django Templates + Bootstrap 5 + Bootstrap Icons + custom CSS
- **Database:** SQLite (swap to PostgreSQL/MySQL by editing `DATABASES` in `settings.py`)

---

## Quick start

```bash
# 1. Create and activate a virtualenv (optional but recommended)
python3 -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Migrate and seed mock data (20 agents, ~80 sessions, 50 flags)
python manage.py migrate
python manage.py seed_demo_data --fresh

# 4. (Optional) Create a Django admin user to edit rules / data live
python manage.py createsuperuser

# 5. Run the server
python manage.py runserver 0.0.0.0:8000
```

Open `http://localhost:8000/` — you land on the Risk Inbox straight away.

### Key routes

| Route                  | Purpose                                              |
|------------------------|------------------------------------------------------|
| `/`                    | Risk Inbox dashboard                                 |
| `/flag/<id>/`          | Forensic Timeline drill-down + Resolution form       |
| `/rules/`              | Rules Engine / Logic Dictionary                      |
| `/audit/`              | Immutable audit trail                                |
| `/admin/`              | Django admin (edit rules, agents, modules, etc.)     |

---

## Database design

Maps directly onto the Project 6 spec (see `compliance/models.py`):

```
┌─ ComplianceRule ─────────────┐  The Logic Dictionary
│ rule_id (PK), rule_name,     │  parameter_json drives the rules engine
│ parameter_json, severity,    │  (e.g. {"detector": "speeding",
│ is_active, created_at        │         "speed_ratio_threshold": 0.2})
└──────────────────────────────┘

┌─ FlaggedSession ─────────────┐  The Inbox Queue
│ flag_id (PK), session (FK),  │  one row per (session × rule_violated)
│ agent (FK), rule_violated,   │
│ flag_timestamp, evidence,    │
│ resolution_status,           │
│ leaderboard_points_revoked,  │  Automated Penalty System fields
│ streak_shield_locked         │
└──────────────────────────────┘

┌─ ComplianceAuditLog ─────────┐  The Immutable Record
│ audit_id (PK), flag (FK),    │  append-only; admin deletion blocked
│ manager_name, action_taken,  │
│ manager_justification_notes, │
│ timestamp                    │
└──────────────────────────────┘
```

Supporting models that feed the engine: `Agent`, `TrainingModule`,
`TrainingSession`, `TelemetryEvent`.

---

## Rules Engine

All rules are stored in the DB. The scanner in `compliance/services.py`
iterates `ComplianceRule.objects.filter(is_active=True)`, reads each rule's
`parameter_json["detector"]` key, and dispatches to a detector function:

| Detector key              | Rule (from spec)                                                     |
|---------------------------|----------------------------------------------------------------------|
| `speeding`                | R1: completion time < `speed_ratio_threshold` × company average      |
| `pattern_guessing`        | R2: quiz finished in ≤ `max_quiz_seconds` with ≤ `max_score_percent` |
| `distraction`             | R3: tab switches > `max_tab_switches` in a sprint                    |
| `perfect_score_too_fast`  | Bonus: completed < `min_time_seconds` but still scored 100%          |

Adding a new rule = adding a row in `ComplianceRule` (no redeploy) or, for a
new algorithm, a new function + `DETECTORS` entry in `services.py`.

### Automated Penalty System

On creation of a High-severity flag the system automatically:
- marks `leaderboard_points_revoked = True`
- locks the agent's streak shield (`streak_shield_locked = True`)

Both are reverted if the manager later approves the session as a false alarm.

---

## Layout

```
fraud_auditor/            # Django project package (settings, urls, wsgi)
compliance/               # The app
├── models.py             # Spec DB design + supporting telemetry models
├── services.py           # Dynamic rules engine + resolve_flag + stats
├── views.py              # Risk Inbox, Forensic Timeline, Rules, Audit
├── forms.py              # ResolveFlagForm
├── urls.py
├── admin.py              # Django admin config (audit log is delete-protected)
├── management/commands/
│   └── seed_demo_data.py # `python manage.py seed_demo_data --fresh`
├── templates/compliance/
│   ├── base.html
│   ├── risk_inbox.html
│   ├── forensic_timeline.html
│   ├── rules_list.html
│   └── audit_log.html
└── static/compliance/app.css
```

---

## Running on a FUSE mount (optional)

If you're running this on a filesystem where SQLite complains about `disk I/O
error` (some FUSE mounts / shared folders disallow SQLite's file locks), set
`DATABASE_PATH` to a path on a native filesystem:

```bash
DATABASE_PATH=/tmp/fraud_auditor.sqlite3 python manage.py migrate
DATABASE_PATH=/tmp/fraud_auditor.sqlite3 python manage.py seed_demo_data --fresh
DATABASE_PATH=/tmp/fraud_auditor.sqlite3 python manage.py runserver
```
