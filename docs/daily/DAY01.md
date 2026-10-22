# Day 1 report

## Run at 2026-09-05T02:50:09.617550+00:00

Requested phases: P1
Baseline gate: PASS
Phases completed this run: P1
Phases NOT completed this run: (none)

### Baseline steps

#### git status - PASS
```
MM .devstate/state.json
A  backend/app/api/domain_schema.py
M  backend/app/main.py
A  backend/app/models/__init__.py
A  backend/app/models/domain.py
 M backend/pytest.ini
A  docs/daily/DAY01.md
A  frontend/src/types/domain.ts
 M scripts/dev_day_runner.py
AM tests/backend/test_domain_models.py
AM tests/backend/test_domain_schema_api.py
 M tests/backend/test_health.py
```

#### backup branch backup/day01-20260905T025005Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 12 source files
```

#### backend: full pytest suite - PASS
```
.........................                                                [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
25 passed, 2 warnings in 0.50s
```

#### frontend: lint - PASS
```
> frontend@0.0.0 lint
> oxlint
```

#### frontend: build - PASS
```
> frontend@0.0.0 build
> tsc -b && vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 18 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/index-CpVaa3eY.css    0.98 kB │ gzip:  0.50 kB
dist/assets/index-BAlOWFri.js   192.05 kB │ gzip: 60.63 kB

✓ built in 350ms
```

### Per-phase verification

#### P1 - PASS
```
....................                                                     [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
20 passed, 5 deselected, 2 warnings in 0.46s
```

## Run at 2026-09-06T04:24:31.821665+00:00

Requested phases: P2
Baseline gate: PASS
Phases completed this run: P2
Phases NOT completed this run: (none)

Note: a first attempt at this run failed one P2 test
(`test_consumer_group_delivers_and_acks_exactly_once_per_consumer`) - it
uncovered a real bug in `app/events/bus.py`'s `ensure_group`, which created
consumer groups starting at Redis stream ID `0` (replay full history) instead
of `$` (start from now). On this long-lived dev Redis instance that meant a
brand new group's first read returned the oldest backlog entries rather than
the message just published. Fixed `ensure_group` to start at `$`, added a
regression test (`test_ensure_group_does_not_replay_pre_existing_backlog`),
and fixed a related bug in the `test_read_new_blocks_until_publish` test
itself (it was using `XRANGE`, which returns oldest-first, to find "the
current tail" - added a proper `latest_id()` helper using `XREVRANGE`
instead). Re-ran the full suite and the P2 phase gate 3x in isolation with no
flakiness before treating this phase as complete. See
`app/events/bus.py`, `tests/backend/test_event_bus.py`.

### Baseline steps

#### git status - PASS
```
M .gitignore
 M backend/pyproject.toml
 M backend/pytest.ini
 M backend/requirements.txt
 M docker/backend.Dockerfile
 M docs/daily/DAY01.md
 M scripts/dev_day_runner.py
 M tests/backend/test_domain_models.py
?? backend/alembic.ini
?? backend/app/db/models.py
?? backend/app/events/
?? backend/migrations/
?? tests/backend/conftest.py
?? tests/backend/test_db_reconnect.py
?? tests/backend/test_event_bus.py
?? tests/backend/test_migrations.py
?? tests/backend/test_redis_reconnect.py
```

#### backup branch backup/day01-20260906T042413Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 25 source files
```

#### backend: full pytest suite - PASS
```
..................................                                       [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
34 passed, 2 warnings in 6.99s
```

#### frontend: lint - PASS
```
> frontend@0.0.0 lint
> oxlint
```

#### frontend: build - PASS
```
> frontend@0.0.0 build
> tsc -b && vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 18 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/index-CpVaa3eY.css    0.98 kB │ gzip:  0.50 kB
dist/assets/index-BAlOWFri.js   192.05 kB │ gzip: 60.63 kB

✓ built in 354ms
```

### Per-phase verification

#### P2 - PASS
```
.........                                                                [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
9 passed, 25 deselected, 2 warnings in 6.89s
```
