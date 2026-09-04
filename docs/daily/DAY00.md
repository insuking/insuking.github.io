# Day 0 report — P0 Bootstrap

Phases: P0
Generated: 2026-09-04 (manual run — see note below)
Gate result: PASS

> Note: `scripts/dev_day_runner.py` requires an existing commit to create its
> git backup branch, so it could not run on Day 0 itself (empty repository).
> The same audit -> implement -> test -> lint -> typecheck -> document ->
> commit sequence was performed manually below; the automated runner takes
> over starting Day 1.

## Completed

- Repository skeleton: `backend/`, `frontend/`, `tests/`, `docs/`, `scripts/`,
  `docker/`.
- FastAPI backend (Python 3.12 target, `backend/app/`) with `GET /health/live`
  and `GET /health/ready` (checks Postgres + Redis connectivity, returns 503
  when either is down).
- React + Vite + TypeScript frontend (`frontend/`) with a mobile-first home
  shell that calls `/health/ready` and shows system status.
- `docker-compose.yml` + `docker/backend.Dockerfile` + `docker/frontend.Dockerfile`
  wiring TimescaleDB, Redis, backend, and frontend together.
- `.devstate/state.json` initialized; `scripts/dev_day_runner.py` (daily
  automation: git status -> backup branch -> gate -> commit -> report)
  implemented for use starting Day 1.
- `docs/MASTER_SPEC.md` (full project spec, source of truth for P0–P22),
  `docs/KAKAO_SETUP.md` (placeholder for P12), root `README.md`.

## Files created

```
backend/pyproject.toml, requirements.txt, requirements-dev.txt, pytest.ini
backend/app/__init__.py, main.py
backend/app/core/__init__.py, config.py
backend/app/api/__init__.py, health.py
backend/app/db/__init__.py, session.py, redis_client.py
frontend/  (Vite react-ts scaffold, App.tsx/App.css/index.css rewritten,
            src/api/client.ts, src/types/health.ts)
tests/backend/__init__.py, test_health.py
tests/frontend/README.md
docker/backend.Dockerfile, docker/frontend.Dockerfile
docker-compose.yml, .env.example, .gitignore
.devstate/state.json
scripts/dev_day_runner.py
docs/MASTER_SPEC.md, docs/KAKAO_SETUP.md, docs/daily/DAY00.md
README.md
```

## Tests run

- Backend: `pytest -q` → **5 passed** (`tests/backend/test_health.py`):
  live returns 200; ready returns 200 with both checks ok; ready returns 503
  when database check fails; ready returns 503 when redis check fails; root
  returns app metadata.
- Backend: `ruff check .` → all checks passed (two intentional broad
  `except Exception` in the readiness probes are annotated `noqa: BLE001`
  with a one-line reason — a health check must never raise).
- Backend: `mypy app` → no issues found (9 source files).
- Frontend: `npm run build` (`tsc -b && vite build`) → succeeded.
- Frontend: `npm run lint` (oxlint) → no issues.

## Integration verification (real, not mocked)

Docker was available in this environment, but `docker compose up` could not
pull base images (`timescale/timescaledb`, `redis`, `python`, `node`) — the
session's outbound egress policy returned `403` on
`production.cloudfront.docker.com` (Docker Hub's CDN), confirmed via the
agent proxy status endpoint as an organization policy denial rather than a
transient error, so it was not retried or routed around. `docker compose
config -q` does validate the compose file successfully.

To still get real integration coverage rather than mocking it, Postgres 16 and
Redis were run as local system services (already installed in the sandbox):

- Created a real `radar` Postgres role + database, started `redis-server`.
- Ran `uvicorn app.main:app` against `DATABASE_URL`/`REDIS_URL` pointed at
  those real services.
- `curl /health/live` → `{"status":"live"}`
- `curl /health/ready` → `200 {"status":"ready","checks":{"database":"ok","redis":"ok"}}`
- Built and served the frontend (`npm run preview`) on `:4173`; verified a
  real CORS preflight from that origin to `/health/ready` succeeds
  (added `CORSMiddleware` to the backend for this).

This proves the actual application code path (FastAPI ↔ real Postgres, real
Redis, and a served frontend origin) end-to-end. What is **not** verified is
Docker Compose's own orchestration (image pulls, container networking,
healthcheck timing) — that remains BLOCKED by the environment's egress
policy and should be re-verified on a machine/CI runner with unrestricted
Docker Hub access before treating "docker compose up" itself as proven.

## Fixes applied

- Initial `ruff check` flagged an unsorted import block in `db/session.py`
  (auto-fixed with `ruff check --fix`) and two blind `except Exception`
  clauses in the readiness probes; annotated as intentional rather than
  suppressed silently.

## Security findings

None yet — no secrets, no external auth, no user input handling exists at
this phase. `.env` is git-ignored; only `.env.example` (no real values) is
committed.

## API status

- KIS / Toss / Upbit / Kakao: not yet integrated (scheduled P3, P5, P7, P12).

## Known problems

- `docker compose up` end-to-end run is environment-BLOCKED here (see above);
  needs verification in an environment with Docker Hub access.
- No frontend test framework yet (Vitest will be introduced at P6, the first
  phase with non-trivial component logic — see `tests/frontend/README.md`).

## UX findings

- N/A — only a placeholder home shell exists; real UX work starts at P6
  (recommendation card) and finishes at P21.

## Next day

Day 1 → P1 (Common Domain Model) + P2 (Database + Event Bus), run via
`python scripts/dev_day_runner.py --day 1` once scheduled.
