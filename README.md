# BrightPath Learning — school-managed learning platform

A web-first, multi-tenant learning platform for children. Schools and educational organizations manage their own classes, teachers, students, courses and assignments. Students see published courses that their school has assigned to their class or directly to them.

# Live project link


#### Note: project is free hosted on render. so render may require a minute to reload the application on first visit.

## Technology

- Python / Django 6.x
- Django REST Framework (versioned `/api/v1/` API)
- SQLite by default for local development
- PostgreSQL in the production Docker Compose stack
- Django templates + responsive CSS for the initial web experience
- Django sessions and CSRF protection for browser authentication
- Gunicorn for production WSGI serving


## Local development (SQLite)

Requires Python 3.11+

```bash
python -m venv venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. The default local database is `db.sqlite3`; no Docker or PostgreSQL is needed for development.

For a quick local demo, after migrations:

```bash
python manage.py seed_demo --password 'ChangeThis-Demo-Password-2024'
```

The command refuses to run when `DEBUG=0`. Demo accounts: `platform-admin`, `school-admin`, `teacher`, `student`, `guardian`; all use the password you supply. These are local demonstration accounts only. Never seed demo accounts in a production environment.

## Main web journeys

- Public landing page and school/organization application: `/` and `/institutions/apply/`
- Platform admin: approve/reject/suspend institution applications at `/platform/institutions/`
- Institution owner/admin: dashboard, create classes, create student accounts, create courses, add lessons, add quiz questions, publish, and assign courses
- Teacher: work in the institution to which they belong; course and class queries are tenant-scoped
- Student: `/student/` shows assigned courses only; lesson progress and quiz scoring are persisted server-side
- Guardian: `/guardians/sign-up/`; the school links the account to a student, and the guardian must explicitly confirm consent before progress summaries become visible
- Internal Django admin: `/admin/`

## REST API (v1)

Session-authenticated endpoints are available under `/api/v1/`:

- `GET /api/v1/me/`
- `GET /api/v1/student/courses/`
- `GET /api/v1/courses/{id}/`
- `GET /api/v1/lessons/{id}/`
- `POST /api/v1/lessons/{id}/quiz/` with `{ "answers": { "<question-id>": <choice-index> } }`
- `PUT/PATCH /api/v1/lessons/{id}/progress/`
- `GET /api/v1/progress/`
- `GET /api/v1/institution/classes/`
- `GET /api/v1/guardian/children/`

The browser API uses Django session authentication. A production mobile API authentication scheme (for example short-lived access tokens with refresh-token rotation) should be selected and security-reviewed before mobile development; Basic Authentication is intentionally not enabled.

## Production Docker / PostgreSQL

Docker Compose is intended for production-like deployment and uses PostgreSQL. It does not publish the web container directly to the public internet; place a TLS reverse proxy/load balancer in front of the `web` service. Set environment variables through a secret manager or deployment environment, not by committing `.env`.

```bash
cp .env.example .env
# Edit .env with unique strong secrets and your actual hostnames.
docker compose up --build -d
```

Required production values: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `POSTGRES_PASSWORD`. `DJANGO_DEBUG` is forced to `0` in Compose. The image bootstraps the initial core migration at build time; migrations are then applied and static files collected on startup. Commit generated migrations to source and stop generating migrations during image builds before production release. For a multi-replica deployment, run migrations as a one-off release step rather than concurrently in every replica.

Before real production, configure TLS, a production email provider, backups and restore tests, object storage for user media, monitoring/error reporting, rate limits at the edge, and an explicit media-retention policy. SQLite is not intended for multi-worker production.

## Security and child-safety foundations included

- Institution membership and role model; tenant-scoped course/class/student queries
- Institution application remains pending until platform approval
- Server-side course assignment and class/grade eligibility checks
- Student answer keys are excluded from student-facing lesson APIs; quiz scores are computed server-side
- Server-authoritative reward ledger with idempotent reward events
- School-created student accounts require a password change before app use
- Guardian-child access requires a link and explicit guardian consent before progress is exposed
- CSRF protection, secure session cookie settings, production HTTPS redirect/HSTS settings, JSON-only API renderer in production, request throttling, upload/body size limits, browser security headers, and audit events for sensitive actions
- No public student profiles, child-to-child direct messaging, public leaderboards or third-party analytics in the initial version

## Important production-hardening work still required

This is an initial implementation foundation, not a certification that the system is safe for live child data. Before real use:

1. Add a verified guardian invitation flow (email delivery, identity checks appropriate to the jurisdiction, expiry/reissue, and consent records).
2. Complete staff invitation acceptance, student bulk import with dry-run/rollback, class/year rollover, account recovery and deletion workflows.
3. Add automated tests for cross-tenant object access, role escalation, student/guardian access, quiz integrity, CSRF, upload validation and rate limits.
4. Perform an independent security review and threat model; configure production database credentials, TLS, backups, monitoring and incident response.
5. Define child privacy and guardian consent requirements for every jurisdiction in which the service operates, plus content review/licensing policies.
6. Move media to private object storage with authorized access; avoid accepting arbitrary media URLs without a trusted-domain policy and SSRF review.
7. Add email delivery and secure password reset; avoid distributing temporary passwords through insecure channels.
8. Consider per-tenant audit access, audit retention, field-level export controls, CSP, session expiry policy, and MFA for privileged staff.
9. Add tests for PostgreSQL and run `python manage.py check --deploy` with real deployment environment variables.



### API schema and interactive docs

- OpenAPI schema: `/api/schema/`
- Swagger UI: `/api/docs/`
- ReDoc: `/api/redoc/`

These endpoints use `drf-spectacular` and the DRF `AutoSchema` integration.

### Announcements and notifications

Institution owners/administrators can send announcements to all enrolled institution teachers
and students, all teachers, all students, or one selected teacher/student. Teachers can send to
enrolled students in one of their created or classroom-assigned courses, or all such courses.
Students cannot comment; institution staff can comment on announcement threads. Recipient read
state drives the notification bell badge.
