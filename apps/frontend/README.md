# Frontend

React + TypeScript, built with Vite. Run commands from the repository root:

- `pnpm dev:web` starts the frontend at http://projecthelios.localhost through Portless.
- `pnpm build:frontend` type-checks and builds to `apps/frontend/dist`.
- `pnpm typecheck` checks TypeScript; `pnpm lint:frontend` runs Oxlint.

The Vite development server proxies `/api` to Django at `127.0.0.1:8000`.
Use relative `/api/...` URLs for backend requests. Production hosting must
route `/api` to the backend separately; Vite's development proxy is not bundled.
