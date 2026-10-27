# Gannet web frontend

The React/TypeScript interface for Gannet that talks to its Python backend.

## Setup

```powershell
cd web
npm ci
```

`postinstall` runs `patch-package`. The frontend build requires Node.js 20.19.x or newer in the 20.x line, or Node.js 22.12 or newer.
Node.js 22.12+ is recommended.

## Development server

```powershell
$env:PROXY_HOST = "127.0.0.1:5000"
npm run dev
```

`PROXY_HOST` is the Gannet instance the dev server proxies `/api`, `/vod`, `/clips` and other backend routes to. It defaults to `localhost:5000`, the unauthenticated internal port of a Gannet process on the same host. Port 5000 is loopback-only; a remote
backend cannot be reached through it. Keep this development server on a trusted
network: its proxy exposes the trusted internal API without public-listener
authentication.

## Commands

| Command | What it does |
| ------- | ------------ |
| `npm run build` | Production build with the `/BASE_PATH/` placeholder |
| `npm run build:native` | Production build for the native install, served from `/`. Required for the native server to serve the UI |
| `npm run lint` | ESLint plus the Playwright spec lint |
| `npm run lint:fix` | ESLint with `--fix` |
| `npm run prettier:write` | Format sources |
| `npm run i18n:extract` | Extract `t()` keys into `public/locales/en/` |
| `npm run i18n:extract:ci` | Same, but fails if the locale files are out of date |

## E2E tests

```powershell
npx playwright install chromium   # once
npm run e2e:build
npm run e2e                      # run after a successful build
npm run e2e:ui                    # interactive UI for debugging
```

## Conventions

- All user-facing strings go through `react-i18next`. English strings live in `public/locales/en/`, organized by namespace (`views/live`, `common`, ...). Never hardcode display text in a component.
- UI primitives are Radix UI/shadcn components in `src/components/ui/`, styled with TailwindCSS and the `cn()` helper.
- TypeScript runs in strict mode; avoid `any`.

The full conventions, including the generated-file rules, are in [AGENTS.md](../AGENTS.md).
