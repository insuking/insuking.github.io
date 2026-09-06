# Day 5 report

## Run at 2026-09-06T15:13:39.594705+00:00

Requested phases: P9
Baseline gate: PASS
Phases completed this run: P9
Phases NOT completed this run: (none)

### Baseline steps

#### git status - PASS
```
M backend/app/integrations/upbit/rest_client.py
 M backend/app/radar/state.py
 M docs/UPBIT_NOTES.md
 M tests/backend/test_recommendation_engine.py
?? backend/app/radar/crypto_state.py
?? tests/backend/test_crypto_state.py
?? tests/backend/test_crypto_universe.py
```

#### backup branch backup/day05-20260906T151311Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 70 source files
```

#### backend: full pytest suite - PASS
```
......................................................................ss [ 40%]
........................................................................ [ 80%]
....ss............ss................                                     [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
174 passed, 6 skipped, 2 warnings in 21.14s
```

#### frontend: lint - PASS
```
> frontend@0.0.0 lint
> oxlint

src/hooks/useCountdown.ts:16:5: warning react(set-state-in-effect): Calling setState synchronously within an effect can trigger cascading renders help: Effects should synchronize React with external systems. Calling setState synchronously inside an effect starts another render and is usually unnecessary. Derive the value during render, initialize state directly, or update it from the event that caused the change. Use an effect only when synchronizing with an external system.
```

#### frontend: test - PASS
```
> frontend@0.0.0 test
> vitest run


 RUN  v5.0.0 /home/user/insuking.github.io/frontend


 Test Files  1 passed (1)
      Tests  5 passed (5)
   Start at  15:13:34
   Duration  1.27s (environment 60%, tests 20%, transform 8%, setup 7%, import 4%, worker 1%)
```

#### frontend: build - PASS
```
> frontend@0.0.0 build
> tsc -b && vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 21 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/index-D0xQvyeJ.css    2.56 kB │ gzip:  0.88 kB
dist/assets/index-CFxoXUCA.js   196.20 kB │ gzip: 61.75 kB

✓ built in 424ms
```

### Per-phase verification

#### P9 - PASS
```
...........                                                              [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
11 passed, 169 deselected, 2 warnings in 0.34s
```

