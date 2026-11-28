# EcoShift frontend

The landing page and dashboard for EcoShift: CAISO day-ahead electricity prices for California datacenter campuses (published hours, then a three-day model forecast), the cheapest time windows for a job, and a planner that shows what waiting saves in dollars.

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

### Run against the local Python API

`src/server.py` serves the same `/forecast` and `/windows` the Lambda will, from the repo's Python code:

```bash
python -m src.server                                               # from the repo root; http://localhost:8000
echo "NEXT_PUBLIC_ECOSHIFT_API_URL=http://localhost:8000" > frontend/.env.local
```

Restart `npm run dev` after changing `.env.local`. The forecast is still synthetic until the ML pipeline lands, so the "Sample data" label stays.

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

The UI is written against the shapes in `lib/api/types.ts` (prices in $/MWh, which can be negative; costs
in dollars). With the deployed API, `lib/api/carbon-v1.ts` maps its `/v1/sites`, `/v1/forecast` and
`/v1/windows` responses onto them, so that file is the only place that knows the wire format. The sample
client (`lib/mock/`) builds the same shapes, labelled `data_source: "synthetic"`.

Notes:

- `/v1/forecast` gives every hour, each marked `published` (CAISO has already published that day-ahead price) or `forecast` (the model's estimate). The chart draws the boundary and the table shows the column.
- Job cost is price x kWh / 1000, so the planner has a power-draw field (kW, default 8).
- The campus list comes from `/v1/sites`; the first one it returns is used until someone picks another.
- When no window fits before the deadline, the dashboard accepts either an empty `windows` list or an error response.
- The original `createHttpClient` (a `/forecast?region=` contract) is left in `lib/api/client.ts` from the first prototype and is not used by the deployed app; it still returns sample sites.

## Conventions

- **Colors** come from tokens in `app/globals.css`; don't put hex values in components. Chart colors are from a palette validated for color blindness in both themes.
- **Times** display in the viewer's time zone.
- **No clock reads during render.** Cache Components is on, so `Date.now()` or `new Date()` during prerender breaks the build. Use `useMinuteClock()` or do the work in an effect.
- **Sample data is always labeled**, driven by the API's `data_source` field, so a demo never passes made-up numbers off as real.
- Logic that produces numbers people rely on (`lib/carbon.ts`, `lib/format.ts`, `lib/cli.ts`) gets unit tests.

## Running against the deployed (ECS) API

`NEXT_PUBLIC_ECOSHIFT_API_MODE=carbon-v1` switches the UI to this repo's `/v1/*` endpoints through
`lib/api/carbon-v1.ts`. The browser calls `/v1/*` on its own origin: on AWS the load balancer routes that
path to the API, and locally `API_PROXY_URL=http://localhost:8000` makes the dev server forward it
(`make web` from the repo root does both). No CORS is needed.

- `data_source` comes from the API: `caiso-day-ahead` for real prices, `synthetic` for the stub models. The
  "Sample data" label shows only for `synthetic`.
