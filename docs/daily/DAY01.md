# Day 1 report

Requested phases: P2
Generated: 2026-09-06T04:24:31.821665+00:00
Baseline gate: PASS
Phases completed this run: P2
Phases NOT completed this run: (none)

## Baseline steps

### git status - PASS
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

### backup branch backup/day01-20260906T042413Z - PASS

### backend: ruff - PASS
```
All checks passed!
```

### backend: mypy - PASS
```
Success: no issues found in 25 source files
```

### backend: full pytest suite - PASS
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

### frontend: lint - PASS
```
> frontend@0.0.0 lint
> oxlint
```

### frontend: build - PASS
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

## Per-phase verification

### P2 - PASS
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
