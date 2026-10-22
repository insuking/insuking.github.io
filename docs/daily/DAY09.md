# Day 9 report

## Run at 2026-09-07T06:02:47.085348+00:00

Requested phases: P17, P18
Baseline gate: PASS
Phases completed this run: P17, P18
Phases NOT completed this run: (none)

### Baseline steps

#### git status - PASS
```
M backend/app/db/models.py
?? backend/app/partial_profit/
?? backend/app/risk/
?? backend/migrations/versions/5af6bb5e53bd_add_risk_states_table.py
?? tests/backend/test_partial_profit_accounting.py
?? tests/backend/test_partial_profit_service.py
?? tests/backend/test_risk_kill_switch.py
?? tests/backend/test_risk_service.py
```

#### backup branch backup/day09-20260907T060206Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 140 source files
```

#### backend: full pytest suite - PASS
```
........................................................................ [ 17%]
......................................................................s. [ 34%]
............ss.......................................................... [ 51%]
........................................................................ [ 68%]
........................................................................ [ 85%]
.sss................................sss......................            [100%]
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
412 passed, 9 skipped, 22 warnings in 30.85s
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
   Start at  06:02:39
   Duration  1.64s (environment 54%, tests 25%, transform 10%, setup 6%, import 4%, worker 1%)
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

✓ built in 495ms
```

### Per-phase verification

#### P17 - PASS
```
...............                                                          [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
15 passed, 406 deselected, 2 warnings in 0.89s
```

#### P18 - PASS
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
25 passed, 396 deselected, 2 warnings in 0.82s
```

