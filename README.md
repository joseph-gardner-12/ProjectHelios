# Project Helios

A pnpm workspace with a React + TypeScript frontend and a Python/Django backend.
Like Staccato Music, pnpm orchestrates development from the repository root;
uv manages Python dependencies and the backend virtual environment.

## Layout

```text
apps/
  frontend/   React + TypeScript + Vite
  backend/    Django + SQLite, managed with uv
  localization/  Dock-side Python localization service scaffold, managed with uv
```

The workspace also reserves `libs/*` for future shared JavaScript/TypeScript packages.
Python dependencies belong in `apps/backend/pyproject.toml`, not package.json.

## Project planning

- [Localization setup, commands, and implementation guide](docs/localization.md)
- [Accepted architecture: UWB X/Y, barometric Z, SiK, and ArduPilot (ADR-0001)](docs/adr/0001-uwb-sik-ardupilot-navigation.md)
- [System plan, hardware/software inventory, and team responsibilities](docs/planning/system-plan.md)
- [Day-by-day delivery roadmap](docs/project-roadmap.md)
- [Dock hardware and deployment verification](docs/research/dock-hardware-verification.md)

## Quick start

Install Node.js 24+ (the `.nvmrc` selects 24), pnpm 11.2.2, and uv.
The backend pins Python 3.14; uv can download it if it is not installed.

```sh
pnpm install
pnpm setup
pnpm dev
```

Open http://projecthelios.localhost. Portless maps this hostname to Vite on port 5173,
matching Staccato Music's HTTP development proxy setup. Django runs at http://127.0.0.1:8000.
The frontend proxies `/api` to Django; `/api/health/` returns a JSON health response.
Ctrl+C stops both development servers. Ports are fixed so conflicts fail visibly.

`pnpm dev` and `pnpm dev:web` ensure the Portless proxy and hostname alias are ready.
The shared proxy stays running when the apps stop. Its first start on port 80 may
prompt for administrator access. The setup preserves other projects' aliases.
Direct access at http://localhost:5173 also works.

## Development and production

| Environment | Website | Routing configuration |
| --- | --- | --- |
| Local development | `http://projecthelios.localhost` (or `http://localhost:5173`) | Portless alias in `package.json`; SPA fallback and local API proxy in `apps/frontend/vite.config.ts` |
| Production | `https://projecthelios.dev` (currently redirects to `https://www.projecthelios.dev`) | Vercel domain settings and `apps/frontend/vercel.json` |

For local development, run `pnpm dev` or `pnpm dev:web`. Direct links such as
`http://projecthelios.localhost/control` are served by Vite's SPA fallback.
The `.localhost` URLs refer to the computer running the development servers.

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

`pnpm setup` installs backend dependencies and applies migrations to a local,
ignored SQLite database. No external database service is needed for this starter.
Commit both `pnpm-lock.yaml` and `apps/backend/uv.lock` when changing dependencies.
For reproducible installs, use `pnpm install --frozen-lockfile` and
`uv sync --locked --project apps/backend`.

## Commands

| Command | Purpose |
| --- | --- |
| `pnpm dev` | Start both apps |
| `pnpm setup:portless` | Start the HTTP proxy and register projecthelios.localhost |
| `pnpm dev:web` | Start only the frontend |
| `pnpm dev:backend` | Start only Django |
| `pnpm backend:manage <command>` | Run a Django management command |
| `pnpm backend:migrate` | Apply database migrations |
| `pnpm backend:shell` | Open the Django shell |
| `pnpm check` | TypeScript, frontend/backend lint, Django checks and backend tests |
| `pnpm build` | Type-check and build the frontend |
| `pnpm setup:localization` | Install the localization environment and dev tools |
| `pnpm localization:simulate` | Reserved simulation command; implementation pending |
| `pnpm localization:replay` | Reserved replay command; implementation pending |
| `pnpm localization:run` | Reserved hardware runtime command; implementation pending |
| `pnpm test:localization` | Run pytest; exits 5 until localization tests are added |
| `pnpm lint:localization` | Lint the localization scaffold |

Localization is currently structure-only and is not included in `pnpm dev`,
`pnpm setup`, or `pnpm check`. Its Python modules are empty; simulation, replay,
and hardware commands will fail until the CLI is implemented. See the
[localization guide](docs/localization.md) for details.

Add frontend packages with `pnpm --filter @project-helios/frontend add <package>`.
Add root development tools with `pnpm add -Dw <package>`.
Add Python packages with `uv add --project apps/backend <package>`.

The backend settings are for local development. Production needs deployment
settings (secret key, debug disabled, allowed hosts, database and static files)
and a web server that serves the frontend build and routes `/api` to Django.

Tooling references: [pnpm workspaces](https://pnpm.io/workspaces),
[Vite](https://vite.dev/guide/), and [Django](https://docs.djangoproject.com/en/6.0/).
