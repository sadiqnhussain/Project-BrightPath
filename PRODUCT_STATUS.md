# Product status — first web build

## Implemented in source

- Responsive landing page and school/organization application form
- Pending institution state and platform-admin approve/reject/suspend flow
- User roles, institution membership, academic years, classes/grades and teacher assignment
- Staff invitations with expiry and email delivery (console backend in local development)
- School-managed student accounts with required password change at first sign-in
- Institution-scoped course and lesson creation, multiple-choice quiz question authoring, publishing, and school review when teacher content approval is enabled
- Class or individual course assignments, grade eligibility and server-side student authorization
- Student dashboard, course path, lessons, quiz submission, persisted progress and idempotent reward events
- Guardian signup, email verification, school-created guardian link request, explicit guardian consent and progress summaries
- School-level progress summaries and safety/content reporting queue
- Versioned REST API for identity, student courses, course/lesson detail, quiz submissions, progress, class list and guardian summaries
- SQLite default for local development; PostgreSQL settings and production Docker Compose
- Django admin, password validators, login lockout, CSRF, security headers, CSP for first-party UI, request throttles and audit-event model

## Intentionally not implemented yet

- Native mobile app
- Password-reset workflow and school-assisted recovery UI
- CSV student import/export with dry-run, validation report and rollback
- Student transfer / academic-year rollover workflow
- Full course editing/version-diff UI after publication
- Upload pipeline and private object storage for media (lesson media currently uses approved-provider HTTPS links)
- Guardian invite email and reissue management UI; the school links an already registered, email-verified guardian
- Legal review and jurisdiction-specific guardian/child consent requirements
- Full notification delivery, analytics, live classes, child-to-child messaging, payments or AI tutoring
- Production-grade monitoring, central audit log shipping, backups/restore automation and deployment-specific TLS proxy

## Verification status

- Python source files pass `compileall` syntax compilation.
- Template URL names were checked against `config/urls.py`; no missing URL names were found.
- Automated tests are included under `core/tests.py` for tenant scoping and quiz answer protection.
- Django is not installed in the authoring environment and the package index was unreachable, so Django system checks, migration execution, test execution, Docker build and browser/device tests have **not** been run here.

## First verification pass on a machine with package access

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py check
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

Before production, commit generated migration files and run `python manage.py check --deploy` with production environment variables. Run the test suite against both SQLite and PostgreSQL in CI.
