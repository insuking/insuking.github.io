# Day 2 report

## Run at 2026-09-06T10:43:37.297102+00:00

Requested phases: P3
Baseline gate: PASS
Phases completed this run: P3
Phases NOT completed this run: (none)

### Baseline steps

#### git status - PASS
```
M .env.example
 M backend/app/core/config.py
 M backend/pyproject.toml
 M backend/requirements-dev.txt
 M backend/requirements.txt
?? backend/app/integrations/
?? docs/KIS_SETUP.md
?? tests/backend/test_kis_auth.py
?? tests/backend/test_kis_integration.py
?? tests/backend/test_kis_parsing.py
?? tests/backend/test_kis_rest_client.py
?? tests/backend/test_kis_ws_client.py
```

#### backup branch backup/day02-20260906T104315Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 37 source files
```

#### backend: full pytest suite - PASS
```
....................................ss..................                 [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
54 passed, 2 skipped, 2 warnings in 12.16s
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

✓ built in 471ms
```

### Per-phase verification

#### P3 - PASS
```
.....ss...............                                                   [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
20 passed, 2 skipped, 34 deselected, 2 warnings in 5.36s
```

