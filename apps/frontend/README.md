# Frontend

React + TypeScript, built with Vite. Run commands from the repository root:

- `pnpm dev:web` starts the frontend at http://projecthelios.localhost through Portless.
- `pnpm build:frontend` type-checks and builds to `apps/frontend/dist`.
- `pnpm typecheck` checks TypeScript; `pnpm lint:frontend` runs Oxlint.

The Vite development server proxies `/api` to Django at `127.0.0.1:8000`.
Use relative `/api/...` URLs for backend requests. Production hosting must
route `/api` to the backend separately; Vite's development proxy is not bundled.

## Site structure

| URL | Page |
| --- | --- |
| `/` | Landing page |
| `/about` | About |
| `/team` | Meet the team |
| `/control` | Control |

React Router renders each page inside `src/components/SiteLayout.tsx`, which owns
the shared header, navigation, footer, and accessible route focus handling.
Page content lives in `src/pages/`; shared color tokens and responsive styles live
in `src/index.css`. About, team, and control are placeholders for future content.
Unknown URLs display a not-found page within the same layout.

The layout uses fluid spacing and type, a capped content width, wrapping navigation,
and a single-column mobile layout. The footer follows page content and stays at the
bottom of short pages. Keyboard focus, skip navigation, and reduced motion are supported.

Production hosting must serve `index.html` for frontend routes so direct links
and refreshes work, while keeping `/api` requests routed to Django.

Accent tokens use Clemson Orange (`#F56600`) and Regalia (`#522D80`), from
[Clemson’s official palette](https://www.clemson.edu/brand/color/). Orange is used
for keyboard focus against the dark background; purple selection uses light text.
