# Project Helios

A pnpm workspace with a React + TypeScript frontend and a Python/Django backend.
Like Staccato Music, pnpm orchestrates development from the repository root;
uv manages Python dependencies and the backend virtual environment.

## Layout

```text
apps/
  frontend/   React + TypeScript + Vite
  backend/    Django + PostgreSQL, managed with uv
  localization/  Dock-side Python runtime with backend-connected dummy mode, managed with uv
```

The workspace also reserves `libs/*` for future shared JavaScript/TypeScript packages.
Python dependencies belong in `apps/backend/pyproject.toml`, not package.json.

## Project planning

- [Backend setup, GitHub deployment, and manual setup steps](docs/backend-deployment.md)
- [Backend architecture and continuation status (ADR-0002)](docs/adr/0002-digitalocean-backend-foundation.md)
- [Localization setup, commands, and implementation guide](docs/localization.md)
- [Accepted architecture: UWB X/Y, barometric Z, SiK, and ArduPilot (ADR-0001)](docs/adr/0001-uwb-sik-ardupilot-navigation.md)
- [System plan, hardware/software inventory, and team responsibilities](docs/planning/system-plan.md)
- [Day-by-day delivery roadmap](docs/project-roadmap.md)
- [Dock hardware and deployment verification](docs/research/dock-hardware-verification.md)

## Quick start

Install Node.js 24+, pnpm 11.2.2, uv, PostgreSQL 16, and Redis.
On macOS, install the services with `brew install postgresql@16 redis`.
The backend pins Python 3.14; uv can download it if needed.

```sh
pnpm install --frozen-lockfile
```

**Solo (like Staccato Music):** add this repository folder to Solo and load/trust
`solo.yml`. Start all processes for separate database, Redis, backend, worker,
frontend, and dummy localization panes. Setup, migrations, and local credentials
are handled automatically.

**Terminal alternative:**

```sh
pnpm dev
```

Open http://127.0.0.1:5173/control. Sign in with a Clemson-format email and
`SeniorDesign`. Ctrl+C stops all six services; local data is kept in ignored
`.helios/dev/`. Use either Solo or `pnpm dev`, not both simultaneously.
See [control setup](docs/control-setup.md) for manual checks and Pi setup.

## Development and production

| Environment | Website | Routing configuration |
| --- | --- | --- |
| Local development | `http://127.0.0.1:5173` | SPA fallback and local API/WebSocket proxy in `apps/frontend/vite.config.ts` |
| Production | `https://projecthelios.dev` (currently redirects to `https://www.projecthelios.dev`) | Vercel domain settings and `apps/frontend/vercel.json` |

Solo and `pnpm dev` start the complete local control stack. For frontend-only
work, `pnpm dev:web` also registers the optional Portless hostname
`http://projecthelios.localhost`. Its first proxy start may require administrator
access. The `.localhost` URLs refer to your own computer.

For production, set the Vercel project's **Root Directory** to `apps/frontend`.
The configuration there selects Vite, runs `pnpm run build`, and publishes `dist`.
It rewrites `/control`, `/about`, and `/team` to `/index.html` so React Router can
render direct links and refreshes. Trailing slashes are normalized away.
New frontend routes must be added to this rewrite list. Assets and `/api` are not
included in these rewrites; configure production backend routing separately.

Keep `projecthelios.dev` and `www.projecthelios.dev` assigned to the production
Vercel project. Do not add them to the Portless alias or Vite's local allowed hosts.
Commit and deploy configuration changes through the production deployment workflow;
editing local files does not update the live site.

A sitemap is separate from routing: it lists canonical production URLs for search
engines. It must not include `.localhost` URLs and does not fix direct-link 404s.

`pnpm setup` installs dependencies for isolated component work. The complete
Solo and `pnpm dev` workflows use their own local PostgreSQL and Redis processes.
Commit both `pnpm-lock.yaml` and `apps/backend/uv.lock` when changing dependencies.
For reproducible installs, use `pnpm install --frozen-lockfile` and
`uv sync --locked --project apps/backend`.

## Commands

| Command | Purpose |
| --- | --- |
| `pnpm dev` | Start and configure the complete local stack |
| `pnpm pi:setup` | Save standalone Pi connection settings once |
| `pnpm pi` | Start the configured dummy Pi client |
| `pnpm setup:portless` | Start the HTTP proxy and register projecthelios.localhost |
| `pnpm dev:web` | Start only the frontend |
| `pnpm dev:backend` | Start only Django |
| `pnpm backend:manage <command>` | Run a Django management command |
| `pnpm backend:migrate` | Apply database migrations |
| `pnpm backend:shell` | Open the Django shell |
| `pnpm check` | TypeScript, frontend/backend lint, Django checks and backend tests |
| `pnpm build` | Type-check and build the frontend |
| `pnpm setup:localization` | Install the localization environment and dev tools |
| `pnpm localization:simulate` | Run backend-connected dummy telemetry |
| `pnpm localization:replay` | Reserved replay command; implementation pending |
| `pnpm localization:run` | Reserved hardware runtime command; implementation pending |
| `pnpm test:localization` | Run localization protocol and dummy runtime tests |
| `pnpm lint:localization` | Lint the localization scaffold |

Localization dependencies and tests are included in `pnpm setup` and `pnpm check`.
Solo and `pnpm dev` include the dummy client and control lifecycle worker.
Real hardware and replay
commands remain unimplemented. See [control setup](docs/control-setup.md) and the
[localization README](apps/localization/README.md) for the dummy milestone.

Add frontend packages with `pnpm --filter @project-helios/frontend add <package>`.
Add root development tools with `pnpm add -Dw <package>`.
Add Python packages with `uv add --project apps/backend <package>`.

The backend defaults to `config.settings.local` with SQLite. Production uses
`config.settings.production`, PostgreSQL, Redis, Daphne, and Caddy on DigitalOcean;
the frontend remains on Vercel. Deployment assets and GitHub Actions are included,
but provisioning, DNS, SSH secrets, and live verification require the
[manual setup steps](docs/backend-deployment.md). `/api/health/` checks the process;
`/api/ready/` checks PostgreSQL/SQLite and Redis and returns 503 if Redis is not configured.
Authenticated device/browser WebSockets, a five-minute control queue, and durable commands are implemented. See [control setup](docs/control-setup.md) for credentials, Redis, and dummy runtime configuration.

Tooling references: [pnpm workspaces](https://pnpm.io/workspaces),
[Vite](https://vite.dev/guide/), and [Django](https://docs.djangoproject.com/en/6.0/).
