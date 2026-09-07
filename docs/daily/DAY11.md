# Day 11 report

## Run at 2026-09-07T07:13:38.474135+00:00

Requested phases: P21, P22
Baseline gate: PASS
Phases completed this run: P21
Phases NOT completed this run: P22

### Baseline steps

#### git status - PASS
```
M backend/app/api/approvals.py
 M backend/app/core/config.py
 M backend/app/main.py
 M frontend/src/App.css
 M frontend/src/App.tsx
 M frontend/src/api/client.ts
?? backend/app/api/auth.py
?? backend/app/api/dashboard.py
?? backend/app/approval/rate_limit.py
?? backend/scripts/
?? docs/RELEASE_READINESS.md
?? docs/daily/SOAK_LITE.md
?? frontend/src/auth.ts
?? frontend/src/components/NavBar.css
?? frontend/src/components/NavBar.test.tsx
?? frontend/src/components/NavBar.tsx
?? frontend/src/nav.test.ts
?? frontend/src/nav.ts
?? frontend/src/pages/
?? frontend/src/types/auth.ts
?? frontend/src/types/dashboard.ts
?? tests/backend/test_approval_rate_limit.py
?? tests/backend/test_auth_api.py
?? tests/backend/test_dashboard_api.py
```

#### backup branch backup/day11-20260907T071256Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 170 source files
```

#### backend: full pytest suite - PASS
```
........................................................................ [ 13%]
........................................................................ [ 27%]
..................s.............ss...................................... [ 40%]
........................................................................ [ 54%]
........................................................................ [ 67%]
........................................................................ [ 81%]
......................................sss............................... [ 95%]
.sss......................                                               [100%]
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
521 passed, 9 skipped, 22 warnings in 30.86s
```

#### frontend: lint - PASS
```
> frontend@0.0.0 lint
> oxlint

src/hooks/useCountdown.ts:16:5: warning react(set-state-in-effect): Calling setState synchronously within an effect can trigger cascading renders help: Effects should synchronize React with external systems. Calling setState synchronously inside an effect starts another render and is usually unnecessary. Derive the value during render, initialize state directly, or update it from the event that caused the change. Use an effect only when synchronizing with an external system.
src/pages/KakaoCallbackPage.tsx:19:7: warning react(set-state-in-effect): Calling setState synchronously within an effect can trigger cascading renders help: Effects should synchronize React with external systems. Calling setState synchronously inside an effect starts another render and is usually unnecessary. Derive the value during render, initialize state directly, or update it from the event that caused the change. Use an effect only when synchronizing with an external system.
```

#### frontend: test - PASS
```
> frontend@0.0.0 test
> vitest run


 RUN  v5.0.0 /home/user/insuking.github.io/frontend


 Test Files  6 passed (6)
      Tests  26 passed (26)
   Start at  07:13:29
   Duration  2.41s (environment 65%, tests 17%, setup 8%, transform 5%, import 4%, worker 1%)

Environment  jsdom was created 6 times · 4.09s total, 65% of tracked time
             create it once per worker with pool: 'vmThreads' (keeps per-file isolation) or isolate: false (shares it across files)
             learn more: https://vitest.dev/guide/improving-performance#test-environments
```

#### frontend: build - PASS
```
> frontend@0.0.0 build
> tsc -b && vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 34 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/index-DZt4wZvI.css    4.76 kB │ gzip:  1.26 kB
dist/assets/index-DlCrTvTl.js   213.03 kB │ gzip: 65.26 kB

✓ built in 199ms
```

### Per-phase verification

#### P21 - PASS
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
20 passed, 510 deselected, 2 warnings in 2.78s
```

#### P22 - FAIL
```
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.11/site-packages/starlette/testclient.py:53
  /home/user/insuking.github.io/backend/.venv/lib/python3.11/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
530 deselected, 2 warnings in 0.45s
```

