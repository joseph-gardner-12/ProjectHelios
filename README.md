# Project Helios

A pnpm workspace with a React + TypeScript frontend and a Python/Django backend.
Like Staccato Music, pnpm orchestrates development from the repository root;
uv manages Python dependencies and the backend virtual environment.

## Layout

```text
apps/
  frontend/   React + TypeScript + Vite
  backend/    Django + SQLite, managed with uv
scripts/      Workspace tooling
```

The workspace also reserves `libs/*` for future shared JavaScript/TypeScript packages.
Python dependencies belong in `apps/backend/pyproject.toml`, not package.json.

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

Add frontend packages with `pnpm --filter @project-helios/frontend add <package>`.
Add root development tools with `pnpm add -Dw <package>`.
Add Python packages with `uv add --project apps/backend <package>`.

The backend settings are for local development. Production needs deployment
settings (secret key, debug disabled, allowed hosts, database and static files)
and a web server that serves the frontend build and routes `/api` to Django.

Tooling references: [pnpm workspaces](https://pnpm.io/workspaces),
[Vite](https://vite.dev/guide/), and [Django](https://docs.djangoproject.com/en/6.0/).
