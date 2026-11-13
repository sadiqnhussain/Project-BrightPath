# Security and child-safety notes

## Security posture

BrightPath is intended for children and stores learning progress. Treat student identity, class placement, quiz attempts, guardian links, and reports as sensitive data. This codebase establishes baseline controls, but it is not independently audited or certified for production use.

## Controls in this build

- Institution membership is the tenancy boundary. Web queries and student course checks scope objects to the authenticated institution/student.
- Institution applications remain pending until a platform administrator approves them.
- Student course visibility requires a published course, active institution membership, a valid class/student assignment, an available date window, and grade eligibility.
- Student API responses omit answer keys and explanations before submission; the server scores quizzes.
- Reward events are server-side and idempotent per student/event key.
- Student accounts created by a school must change the initial password before using the platform.
- Guardian account email verification precedes school linking; a guardian must explicitly consent to activate the link.
- Login failures are throttled/locked by django-axes; DRF requests are throttled.
- CSRF protection, short-lived browser sessions (four-hour idle timeout; cookie expires when browser closes), secure production cookies, HTTPS redirect/HSTS, security headers, CSP for the first-party web UI, and request-body size limits are configured.
- No public student profiles, child-to-child direct messages, public leaderboards, advertising, or third-party analytics are included.
- Safety reports are tenant-scoped for school reviewers and have a status/resolution workflow.

## Required before live child data

1. **Threat model and independent security review.** Test cross-tenant reads/writes, IDOR, role escalation, session fixation, password guessing, invitation replay, CSRF, XSS, malicious media, and export leakage.
2. **Production configuration.** Unique secret key and database password, TLS reverse proxy, correct forwarded-header behavior, trusted hosts, email provider, backups, tested restore, monitoring, and incident response.
3. **Migrations.** Generate and commit migrations to source control. Do not generate migrations at runtime. The Dockerfile currently bootstraps the initial migration at image build because this source bundle was created without Django available in the build environment; replace that bootstrap step with committed migration files before production release.
4. **Email verification and recovery.** Configure deliverability, SPF/DKIM/DMARC, expiry and reissue controls, account recovery, school-assisted child recovery, and alerting for abuse. A school-issued temporary password must be delivered privately, never in a bulk export or public roster.
5. **Guardian identity and consent.** Email verification alone does not prove legal guardianship. Define stronger verification and consent requirements for the jurisdictions and institutions served; record policy versions and support revocation.
6. **Content moderation.** Review lesson content, external links, copyright, age suitability, accessibility, media captions, and reported concerns. Use a trusted media policy and private object storage for uploaded assets.
7. **Data lifecycle.** Define retention, deletion, export, transfer, backup expiry, and institution offboarding. Minimize fields and access; avoid collecting birth dates or home addresses unless a justified requirement exists.
8. **Production database.** Run automated tests against PostgreSQL in CI. SQLite is local development only; it is not the production concurrency model.
9. **Observability.** Send audit and security events to protected centralized logs. Alert on repeated failed logins, cross-tenant denial spikes, bulk exports, and repeated reports. Do not log passwords, tokens, full quiz answers, or unnecessary child information.
10. **Operational access.** Protect platform admin with MFA at the identity/proxy layer, use least privilege, review staff memberships, and log privileged support access.

## Safe product defaults

- No open messaging between children.
- No public profile, public search for students, or public comparative leaderboard.
- No ad tracking or third-party analytics.
- Keep learning rewards encouraging and non-punitive.
- Guardian summaries are available only for verified and consented links.
- Content concerns are routed to authorized institution reviewers.
- Student-facing APIs should return only the fields required for the current screen.

## Incident response checklist

1. Contain access (disable the affected account/institution or rotate credentials/tokens).
2. Preserve relevant audit logs and timestamps without unnecessarily copying child data.
3. Assess which institution and student records may have been exposed or changed.
4. Follow applicable legal and contractual notification requirements.
5. Patch, test, deploy, and document the incident and corrective actions.
