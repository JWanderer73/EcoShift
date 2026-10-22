<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## EcoShift frontend

- Commands run from `frontend/`: `npm run dev`, `npm run lint`, `npm run typecheck`, `npm test` (Vitest), `npm run test:e2e` (Playwright). Run all four checks before calling a change done.
- `README.md` has the folder layout and the API contract. Keep `lib/api/types.ts` in sync with the CLI's `carbon windows --json` output.
- Window ranking in `lib/carbon.ts` mirrors the CLI's `src/windows.py`. Change both together.
- Cache Components is on: never call `Date.now()` or `new Date()` during render. Use `useMinuteClock()` or an effect.
- Colors come from tokens in `app/globals.css`. No hex values in components.
- Without `NEXT_PUBLIC_ECOSHIFT_API_URL` the app uses sample data; `?scenario=stale|error|slow` imitates backend states.
