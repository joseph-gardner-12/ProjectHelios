---
status: accepted
date: 2026-09-30
---

# ADR-0002: DigitalOcean backend foundation with GitHub deployment

Run the Helios backend on one DigitalOcean Droplet, using Django/Daphne,
PostgreSQL, Redis, Caddy, and systemd. GitHub Actions deploys tested commits from
`main`; the frontend remains on Vercel. This retains StaccatoMusic's Django and
Channels approach while consolidating infrastructure for the project's budget.

Accepted means the architecture is selected, not that deployment has been
verified. Implementation status and evidence are recorded separately below.

## Rationale and precedence

A Basic 1 GiB Droplet is the initial target (approximately $6/month compute,
excluding backups, taxes, and overages). App Platform and separate managed
databases would reduce maintenance but add recurring cost. One server means a
single failure domain, manual operating-system maintenance, and brief restart
downtime. Backups must also exist off-server to protect against server loss.

This decision supersedes the Render hosting recommendation in the historical
[system plan](../planning/system-plan.md). It preserves [ADR-0001](0001-uwb-sik-ardupilot-navigation.md):
localization and flight supervision remain at the dock, independent of the cloud.

## Starting point — 2026-09-30

The repository has a Django health endpoint and admin, development-only settings,
SQLite, and a simulated frontend. It has no application WebSockets, authentication
API, command lifecycle, or deployment workflow. No live infrastructure has been
inspected during this implementation.

## Implementation checkpoint — 2026-09-30

| Area | Status and evidence |
| --- | --- |
| Production configuration | Implemented and locally verified: separate local/test/production settings, required environment validation, PostgreSQL, Redis, secure cookies, explicit origins, and proxy HTTPS handling. See [settings](../../apps/backend/config/settings/production.py) and [configuration tests](../../apps/backend/core/test_configuration.py). |
| ASGI and health | Implemented and tested: Daphne/Channels, unchanged liveness, dependency readiness, release identification header, and rejected public WebSocket upgrades. See [readiness](../../apps/backend/core/readiness.py) and [integration tests](../../apps/backend/core/test_integration.py). |
| Automated checks | Local aggregate checks passed (frontend types/lint and backend checks/tests). The backend suite passes against isolated PostgreSQL 16 and Redis; default SQLite tests intentionally skip the two external-service cases. |
| Production smoke checks | Fresh PostgreSQL migrations, production deployment checks, static collection, live Daphne HTTP requests, Redis/database outage responses and recovery passed locally. A temporary custom-format dump restored successfully with all 18 Django migration records. These are local tests, not cloud evidence. |
| Deployment assets | Implemented; Bash syntax, ShellCheck, GitHub Actionlint, and Caddy configuration validation passed. See [workflow](../../.github/workflows/backend.yml) and [server assets](../../deploy/). Ubuntu bootstrap, systemd behavior, deployment rollback/retention, and backup scheduling still require a disposable server test. No Docker daemon or DigitalOcean test server was available. |
| External setup | Pending verification: Droplet, public DNS/TLS, personal/deployment keys, four GitHub Actions secrets, and first deployment. Existing cloud resources were not inspected. |
| Application features | Deferred: auth API, device credentials, public WebSockets, telemetry, durable commands, configuration, and frontend integration. The control page remains simulated. |

Production deployment checks explicitly exempt HSTS subdomain/preload warnings
W005/W021: the first rollout commits only this API host to one-hour HSTS, not a
domain-wide preload policy. Other deployment warnings fail the release.

**Live deployment:** unverified. No deployed commit, public readiness result,
reboot test, or production restore test has been recorded. The implementation is
in the working tree until reviewed and committed. Do not infer cloud readiness
from the accepted decision or passing local tests.

Use the [numbered manual setup runbook](../backend-deployment.md) for operational
commands. Update this dated checkpoint after each verified milestone, recording
commit/date/results rather than credentials or copied secret configuration.

## Continuation

1. Review and commit the implementation; follow the runbook to provision the
   Droplet, install SSH access and GitHub secrets, and configure DNS.
2. Verify bootstrap reruns preserve credentials/data, then deploy through GitHub
   and record the commit reported by the HTTPS readiness header.
3. On a disposable server, verify failed dependency installation leaves the old
   release running, failed activation restores it, reboot preserves service/data,
   and a database dump restores into a separate database. Configure an off-server
   backup destination; local dump retention alone is not disaster recovery.
4. Develop browser authentication and revocable device credentials, authenticated
   browser/device WebSockets, simulated dock telemetry, durable commands and
   acknowledgments, and reconnect reconciliation.
5. Connect the frontend and then qualify the real dock/hardware integration.

This phase adds no domain models or public WebSocket endpoints. The existing
Django user model and admin remain. Redis is transient distribution; PostgreSQL
owns durable records. Local development retains SQLite; integration checks use
PostgreSQL and Redis. Production data is never copied from a developer database.
