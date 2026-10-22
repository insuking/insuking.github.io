# Kakao Login + Notification Setup

The P12 Kakao integration (`backend/app/integrations/kakao/`) covers OAuth2
login, durable token storage with refresh, and the "send to me" KakaoTalk
notification used to deliver the human-approval link (P13 wires that call
in). No order placement or trading logic lives here - Kakao is purely
identity + notification.

## Where this implementation's contract came from

This sandbox could not reach `developers.kakao.com` directly (blocked by
the session's egress policy, same restriction as KIS/Toss in P3/P5), so the
endpoint paths, OAuth flow, and response fields in `auth.py`/`notify.py`
were verified through web-search snippets of Kakao's own official docs
pages, cross-checked against multiple independent search results rather
than trusted from a single source. What was verified this way:

- Authorization code grant: `POST https://kauth.kakao.com/oauth/token`,
  form-urlencoded, `{grant_type: "authorization_code", client_id,
  redirect_uri, code, client_secret?}` -> `{token_type, access_token,
  expires_in, refresh_token, refresh_token_expires_in, scope}`.
- Refresh grant: same endpoint, `{grant_type: "refresh_token", client_id,
  refresh_token, client_secret?}` -> a new `access_token`/`expires_in`
  always, but `refresh_token`/`refresh_token_expires_in` only when the
  existing refresh token has under one month left - `auth.py`'s `refresh()`
  keeps the prior refresh token/expiry when the response omits them.
- User id lookup: `GET https://kapi.kakao.com/v2/user/me`,
  Bearer-authenticated -> `{id, kakao_account, ...}`; `id` is Kakao's
  numeric per-app user id.
- "Send to me" notification: `POST
  https://kapi.kakao.com/v2/api/talk/memo/default/send`,
  Bearer-authenticated, form-encoded `template_object` (JSON-encoded
  message template) -> `{"result_code": 0}` on success (confirmed directly
  from Kakao's own REST API reference page for this exact endpoint).
  Requires the `talk_message` consent scope granted during Kakao Login.
- `client_secret` is an optional, separately-toggled app setting for Kakao
  (unlike KIS/Toss where the secret is mandatory) - sent only when
  configured.

What was **not** independently confirmed: the full shape of `kakao_account`
inside the user-info response (email, profile fields) - this module only
reads the top-level `id`, so nothing downstream assumes more than that.

## Why there's no fully-automated real-connection test

KIS and Toss use app-only credentials (`client_credentials`), so their
integration tests can obtain a real token with zero human interaction.
Kakao Login's `authorization_code` grant fundamentally requires a real
user's browser consent for the *first* token - there is no way to automate
that step, and this project will not fake it. `test_kakao_integration.py`
is therefore gated on `KAKAO_TEST_REFRESH_TOKEN` in addition to
`KAKAO_CLIENT_ID`/`KAKAO_REDIRECT_URI`: once you've completed the login flow
once by hand (below) and captured a refresh token, that test proves
`refresh()` and `get_user_id()` talk to Kakao's real servers correctly.
Without it, the test stays honestly skipped (BLOCKED), never faked.

## 1. Get credentials

Register an application at the official developer portal
(https://developers.kakao.com) to get:

- The app's **REST API key** (used as `client_id` here)
- A **Client Secret** (optional in Kakao's own settings - only needed if you
  enable it)
- Register a **Redirect URI** for Kakao Login under Product settings

Under the Kakao Login product, request the `talk_message` consent item so
"send to me" notifications are permitted.

## 2. Configure this project

Copy `.env.example` to `.env` (never commit `.env`) and fill in:

```
KAKAO_CLIENT_ID=your_rest_api_key
KAKAO_CLIENT_SECRET=your_client_secret   # optional, only if enabled in Kakao
KAKAO_REDIRECT_URI=https://your-app/callback
```

## 3. Obtaining a refresh token for the integration test (one-time, by hand)

1. Build the consent URL with `KakaoAuth.authorize_url()` (or by hand:
   `https://kauth.kakao.com/oauth/authorize?client_id=...&redirect_uri=...&response_type=code`)
   and open it in a browser; log in and approve, including the
   `talk_message` consent screen.
2. Kakao redirects to your `redirect_uri` with `?code=...` - copy that code.
3. Exchange it once (e.g. in a Python shell) via `KakaoAuth.exchange_code(code)`
   and note the resulting `refresh_token`.
4. Put it in `.env`:

```
KAKAO_TEST_REFRESH_TOKEN=the_refresh_token_from_step_3
```

## 4. Verifying it end-to-end

```
cd backend
source .venv/bin/activate
python -m pytest -q -m P12
```

With only `KAKAO_CLIENT_ID`/`KAKAO_REDIRECT_URI` set, every P12 test runs
except the real-connection one, which stays BLOCKED. Once
`KAKAO_TEST_REFRESH_TOKEN` is also set, `test_kakao_integration.py` runs for
real against Kakao's live servers.
