# Day 10 report

## Run at 2026-09-07T06:36:51.134662+00:00

Requested phases: P19, P20
Baseline gate: PASS
Phases completed this run: P19, P20
Phases NOT completed this run: (none)

### Baseline steps

#### git status - PASS
```
M backend/app/db/models.py
?? backend/app/paper_trading/
?? backend/app/supervisor/
?? backend/migrations/versions/ddb7e52f8fec_add_paper_trading_tables.py
?? tests/backend/test_paper_trading_cost_model.py
?? tests/backend/test_paper_trading_fill_simulator.py
?? tests/backend/test_paper_trading_ledger.py
?? tests/backend/test_paper_trading_replay_engine.py
?? tests/backend/test_supervisor_failure_classifier.py
?? tests/backend/test_supervisor_health_monitor.py
?? tests/backend/test_supervisor_incident_manager.py
?? tests/backend/test_supervisor_reconciliation.py
?? tests/backend/test_supervisor_recovery_manager.py
?? tests/backend/test_supervisor_self_test.py
?? tests/backend/test_supervisor_service_restart.py
```

#### backup branch backup/day10-20260907T063612Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 164 source files
```

#### backend: full pytest suite - PASS
```
........................................................................ [ 14%]
......................................................................s. [ 28%]
............ss.......................................................... [ 42%]
........................................................................ [ 56%]
........................................................................ [ 70%]
........................................................................ [ 84%]
..................sss................................sss................ [ 98%]
......                                                                   [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

test_upbit_auth.py::test_build_headers_without_params_omits_query_hash
test_upbit_auth.py::test_build_headers_with_params_includes_matching_query_hash
test_upbit_auth.py::test_build_headers_generates_a_fresh_nonce_each_call
test_upbit_auth.py::test_build_headers_signature_is_invalid_with_wrong_secret
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/jwt/api_jwt.py:147: InsecureKeyLengthWarning: The HMAC key is 12 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
    return self._jws.encode(

test_upbit_auth.py::test_build_headers_without_params_omits_query_hash
test_upbit_auth.py::test_build_headers_with_params_includes_matching_query_hash
test_upbit_auth.py::test_build_headers_generates_a_fresh_nonce_each_call
test_upbit_auth.py::test_build_headers_signature_is_invalid_with_wrong_secret
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/jwt/api_jwt.py:368: InsecureKeyLengthWarning: The HMAC key is 12 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
    decoded = self.decode_complete(

test_upbit_execution.py: 6 warnings
test_upbit_orders.py: 6 warnings
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/jwt/api_jwt.py:147: InsecureKeyLengthWarning: The HMAC key is 8 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
    return self._jws.encode(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
501 passed, 9 skipped, 22 warnings in 28.53s
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


 Test Files  2 passed (2)
      Tests  13 passed (13)
   Start at  06:36:43
   Duration  1.42s (environment 51%, tests 26%, transform 11%, setup 6%, import 5%)
```

#### frontend: build - PASS
```
> frontend@0.0.0 build
> tsc -b && vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 23 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/index-DcTyR7vU.css    4.28 kB │ gzip:  1.13 kB
dist/assets/index-m2XvAXww.js   203.01 kB │ gzip: 63.33 kB

✓ built in 361ms
```

### Per-phase verification

#### P19 - PASS
```
...........................................................              [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
59 passed, 451 deselected, 2 warnings in 1.71s
```

#### P20 - PASS
```
..............................                                           [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
30 passed, 480 deselected, 2 warnings in 0.96s
```

