# Day 8 report

## Run at 2026-09-06T23:41:36.469232+00:00

Requested phases: P15
Baseline gate: PASS
Phases completed this run: P15
Phases NOT completed this run: (none)

### Baseline steps

#### git status - PASS
```
M .env.example
 M backend/app/core/config.py
 M backend/app/integrations/toss/errors.py
 M backend/app/integrations/toss/rest_client.py
 M backend/requirements.txt
 M docs/TOSS_SETUP.md
 M docs/UPBIT_NOTES.md
 M tests/backend/test_toss_rest_client.py
?? backend/app/execution/
?? backend/app/integrations/toss/execution.py
?? backend/app/integrations/upbit/auth.py
?? backend/app/integrations/upbit/execution.py
?? backend/app/integrations/upbit/orders.py
?? tests/backend/test_toss_execution.py
?? tests/backend/test_toss_execution_integration.py
?? tests/backend/test_upbit_auth.py
?? tests/backend/test_upbit_execution.py
?? tests/backend/test_upbit_execution_integration.py
?? tests/backend/test_upbit_orders.py
```

#### backup branch backup/day08-20260906T234058Z - PASS

#### backend: ruff - PASS
```
All checks passed!
```

#### backend: mypy - PASS
```
Success: no issues found in 116 source files
```

#### backend: full pytest suite - PASS
```
........................................................................ [ 20%]
.....................................s.............ss................... [ 41%]
........................................................................ [ 62%]
........................................................................ [ 82%]
sss................................sss......................             [100%]
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
339 passed, 9 skipped, 22 warnings in 29.23s
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
   Start at  23:41:29
   Duration  1.53s (environment 53%, tests 25%, transform 11%, setup 6%, import 4%)
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

✓ built in 452ms
```

### Per-phase verification

#### P15 - PASS
```
..............s...............s......                                    [100%]
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
35 passed, 2 skipped, 311 deselected, 22 warnings in 1.75s
```

