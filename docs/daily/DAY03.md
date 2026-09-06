# Day 3 report

## Run at 2026-09-06T13:05:17.337540+00:00

Requested phases: P5
Baseline gate: PASS
Phases completed this run: P5
Phases NOT completed this run: (none)

### Baseline steps

#### git status - PASS
```
M .env.example
 M backend/app/core/config.py
?? backend/app/integrations/toss/
?? docs/TOSS_SETUP.md
?? tests/backend/test_toss_auth.py
?? tests/backend/test_toss_integration.py
?? tests/backend/test_toss_rest_client.py
```

#### backup branch backup/day03-20260906T130458Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 53 source files
```

#### backend: full pytest suite - PASS
```
....................................ss.................................. [ 67%]
.....................ss............                                      [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
103 passed, 4 skipped, 2 warnings in 13.59s
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

✓ built in 460ms
```

### Per-phase verification

#### P5 - PASS
```
.....ss............                                                      [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
17 passed, 2 skipped, 88 deselected, 2 warnings in 0.48s
```

