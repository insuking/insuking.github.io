# Day 1 report

Requested phases: P1
Generated: 2026-09-05T02:50:09.617550+00:00
Baseline gate: PASS
Phases completed this run: P1
Phases NOT completed this run: (none)

## Baseline steps

### git status - PASS
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

### backup branch backup/day01-20260905T025005Z - PASS

### backend: ruff - PASS
```
All checks passed!
```

### backend: mypy - PASS
```
Success: no issues found in 12 source files
```

### backend: full pytest suite - PASS
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

✓ built in 350ms
```

## Per-phase verification

### P1 - PASS
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
