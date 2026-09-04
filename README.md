# Multi-Asset Pre-Breakout Radar

24/7 market surveillance for KOSPI/KOSDAQ and Upbit crypto, with human-in-the-loop
approval trading. The system watches markets continuously but never places a new
live order without explicit user approval delivered via Kakao notification.

## Absolute safety defaults

```
LIVE_TRADING = false
TRADING_MODE = PAPER_APPROVAL
LIVE_AUTO    = disabled
```

These are never overridden by code. See the project master spec for the full
human-in-the-loop flow, approval token security model, and risk rules.

## Repository layout

```
backend/   FastAPI service (Python 3.12)
frontend/  React + Vite + TypeScript (mobile-first UI)
tests/     backend/ and frontend/ test suites
docs/      setup guides and daily development reports
scripts/   dev automation (day runner, etc.)
docker/    Dockerfiles for backend/frontend
```

## Local development

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Runs against `DATABASE_URL` / `REDIS_URL` from the environment (see `.env.example`).

Tests: `pytest` (run from `backend/`, picks up `tests/backend` via `pytest.ini`).
Lint: `ruff check .`. Typecheck: `mypy app`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Build: `npm run build`. Lint: `npm run lint`.

### Full stack (Docker Compose)

```bash
docker compose up --build
```

Starts TimescaleDB (Postgres), Redis, the backend API (`:8000`), and the
frontend (`:5173`). See `docs/daily/DAY00.md` for what has been verified so far
and what is still environment-pending.

## Development process

This project is developed phase-by-phase (P0-P22) following the rules in the
project master spec: audit → implement → test → auto-fix (max 5 cycles) →
security check → document → commit, one gate per phase, never skipped.
Current state lives in `.devstate/state.json`.
