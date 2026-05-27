# FMI Benchmark Checker Frontend

Frontend-only checker for junior writers.

It loads the FMI benchmark SQLite DB in the browser, then checks whether a new report title and values violate likely parent-child market sizing logic.

## Run

```bash
cd web
npm install
npm run dev
```

Open the local Vite URL.

## DB input

Use either:

- `fmi_global_benchmarks.sqlite`
- `fmi_global_benchmarks.sqlite.zip`

On Render, the build downloads the ZIP into the static bundle so the browser loads it from the same domain. Locally, run `npm run fetch-db` before `npm run dev`, or use the file upload button.

## Render

The repo root contains `render.yaml`.

Render settings:

- Root directory: `web`
- Build command: `npm run fetch-db && npm run build`
- Publish directory: `dist`

The DB ZIP is not committed to Git. Render downloads it during build.

## Check logic

- New child market cannot be larger than matched parent market.
- New parent market cannot be smaller than matched child market.
- 2026, CAGR, and 2036 are self-checked for internal CAGR math.

All processing runs in the browser. No backend is required.
