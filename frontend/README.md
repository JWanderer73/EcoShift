# EcoShift frontend

The landing page and dashboard for EcoShift: a 48-hour carbon intensity forecast, the best time windows for a job, and a planner that shows how much CO₂ waiting saves.

Next.js (App Router), React, TypeScript, Tailwind CSS. Hosted on Vercel.

## Run it

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

With no API configured, the UI runs on **built-in sample data** and labels it "Sample data" everywhere it appears. To use the real API:

```bash
cp .env.example .env.local
# set NEXT_PUBLIC_ECOSHIFT_API_URL to the API's root URL
```

### Demo and test states

On sample data, add `?scenario=` to any page to imitate the backend:

| Scenario | What you see |
|---|---|
| `stale` | The API is serving an old forecast: stale badge and warning banner |
| `error` | The API is down: error message with a retry button |
| `slow` | 2.5 s responses, to check loading states |

## Commands

Run from `frontend/`.

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript, no emit |
| `npm test` | Unit tests (Vitest, `tests/unit/`) |
| `npm run test:e2e` | End-to-end tests (Playwright, `tests/e2e/`) on desktop and mobile; starts its own dev server on port 3100 |

The first time you run end-to-end tests: `npx playwright install chromium`.

## Layout

```
app/
  page.tsx              landing page (/)
  dashboard/page.tsx    dashboard (/dashboard)
  globals.css           color tokens for light and dark themes
components/
  dashboard/            chart, planner, "right now" card, status badges
  landing/              live forecast card, sparkline, CLI showcase
  ui/                   button, card, badge
lib/
  api/types.ts          the API contract (see below)
  api/client.ts         HTTP client, and the sample-data client used without an API URL
  carbon.ts             window ranking; same logic as the CLI's src/windows.py
  mock/forecast.ts      sample forecast generator
  hooks/                data fetching, clock, element width
  config.ts             named constants (horizon, presets, thresholds)
tests/
  unit/                 logic: ranking, formatting, sample data, CLI command
  e2e/                  user flows on desktop and mobile
```

## API contract

The dashboard calls two `GET` endpoints. Field names match `carbon windows --json` from the [CLI design spec](../docs/superpowers/specs/2026-10-21-carbon-cli-design.md), so the CLI and dashboard share one contract. The types live in `lib/api/types.ts`.

**`GET /forecast?region=CISO`** returns the hourly series the chart draws:

```json
{
  "region": "CISO",
  "generated_at": "2026-10-22T00:06:00Z",
  "stale": false,
  "data_source": "synthetic",
  "points": [{ "start": "2026-10-22T01:00:00Z", "intensity": 287 }]
}
```

`points` holds 48 consecutive hourly values in gCO₂/kWh, starting at the current hour.

**`GET /windows?region=CISO&duration_hours=4&deadline=2026-10-23T18:00:00Z&top=3`** returns the same JSON as `carbon windows --json`: `region`, `generated_at`, `stale`, `data_source`, `job`, `baseline`, and ranked `windows`.

Notes for the API team:

- `/forecast` gives every hour, not just the top windows. The dashboard's chart and draggable job block need it, and so does the chart in the CLI's table output (`--json` doesn't call it).
- When no window fits before the deadline, the dashboard accepts either an empty `windows` list or an error response. The Python stand-in raises an error.
- The browser calls the API directly, so it needs CORS headers allowing the dashboard's Vercel domain.
- The region list (`lib/regions.ts`) matches the CLI: CISO, ERCO, PJM.

## Conventions

- **Colors** come from tokens in `app/globals.css`; don't put hex values in components. Chart colors are from a palette validated for color blindness in both themes.
- **Times** display in the viewer's time zone.
- **No clock reads during render.** Cache Components is on, so `Date.now()` or `new Date()` during prerender breaks the build. Use `useMinuteClock()` or do the work in an effect.
- **Sample data is always labeled**, driven by the API's `data_source` field, so a demo never passes made-up numbers off as real.
- Logic that produces numbers people rely on (`lib/carbon.ts`, `lib/format.ts`, `lib/cli.ts`) gets unit tests.
