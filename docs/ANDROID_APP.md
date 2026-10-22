# Android App (PWA -> TWA)

The user's end goal (see conversation history) is a real Android app. The
fastest, lowest-risk path from an existing React SPA to something
installable from the Play Store is **PWA -> TWA**: make the existing web
app a proper installable Progressive Web App first (P42/P43, already
done - below), then wrap it in a **Trusted Web Activity** (a thin Android
shell that launches the PWA full-screen, no browser chrome, indistinguishable
from a native app once installed) rather than rewriting the UI in
Kotlin/Compose or React Native. The web app stays the single source of
truth; the Android "app" is a few hundred KB of wrapper around it.

This doc is split into what's already built (backend/frontend changes,
verifiable right now) and what only the user can do (real accounts,
real domains, real signing keys - none of which this sandbox has network
or credential access to set up).

## Already built (P42/P43)

- **Installable PWA** (`frontend/vite.config.ts`, `vite-plugin-pwa`):
  `manifest.webmanifest` (name/icons/theme color/`display: standalone`)
  and a generated service worker. Icons live in `frontend/public/icons/`,
  rendered from the existing brand mark (`favicon.svg`) at 192/512px, plus
  maskable variants for Android's adaptive-icon system and an
  `apple-touch-icon.png` for iOS "Add to Home Screen".
- **The service worker precaches only the static app shell** - JS/CSS/
  fonts/icons/HTML from the build output. It has **zero runtime-caching
  rules for the backend API** (`vite.config.ts`'s `workbox.runtimeCaching:
  []`, deliberately empty with a comment explaining why). Every screen in
  this app shows live financial/approval data - positions, pending
  approvals, prices, risk state - and a service worker silently serving a
  stale cached response for any of that would show the user a wrong
  balance or a decided-looking approval that's actually gone. If you ever
  add a runtime-caching rule here, re-read that comment first.
- **CORS is now configurable** (`backend/app/core/config.py`'s
  `CORS_EXTRA_ORIGINS`, comma-separated, read by `app/main.py`) - the
  local dev origins (`localhost:5173`/`4173`) are always allowed; this
  adds whatever public origin you end up serving the frontend from.
- **The frontend's API origin is now a Docker build arg**
  (`docker/frontend.Dockerfile`'s `VITE_API_BASE_URL`, wired through
  `docker-compose.yml`'s `frontend.build.args`). This matters because
  Vite bakes `VITE_*` env vars into the built JS at *build* time, not
  read at container start - the existing setup silently baked in
  `http://localhost:8000`, which works from a browser on the same machine
  but is unreachable from a phone. Set `VITE_API_BASE_URL` in `.env` to
  the backend's real public origin and rebuild
  (`docker compose build frontend`) once you have one (Step 2 below).
- **An optional `cloudflared` service** in `docker-compose.yml`, gated
  behind the `android` Compose profile so it never starts during your
  normal `docker compose up -d` - only `docker compose --profile android
  up -d` starts it. Needs `CLOUDFLARE_TUNNEL_TOKEN` in `.env` (Step 1).
- **A placeholder `frontend/public/.well-known/assetlinks.json`** - the
  file Android checks to verify your app and your website are the same
  owner (Digital Asset Links). It has two fields you'll fill in once you
  have a signed app (Step 4): `package_name` and
  `sha256_cert_fingerprints`.

None of this is reachable from outside your machine yet - it's all
waiting on Step 1.

## What only you can do (this sandbox has no network/credential access
for any of this)

### Step 1 - Get a domain you control

Digital Asset Links verification (what lets the TWA open without a URL
bar - the entire point of wrapping a PWA instead of just bookmarking it)
requires hosting a static JSON file at a **stable** public HTTPS domain
you control. A random `*.trycloudflare.com` quick-tunnel hostname changes
every time you restart `cloudflared`, so it cannot be used for the real
app - only for a quick manual check that the tunnel itself works.

If you don't already own a domain, buy a cheap one from any registrar
(Cloudflare's own registrar sells most `.com`/`.dev`/etc. at close to
wholesale price, with no markup, which pairs conveniently with everything
below). You do not need anything expensive - any TLD works.

### Step 2 - Cloudflare Tunnel (chosen approach - free, no port forwarding)

On the Windows machine that runs `docker compose`:

1. Create a free Cloudflare account and add your domain to it (Cloudflare
   becomes your DNS provider - it gives you nameservers to set at your
   registrar if you bought the domain elsewhere).
2. Install `cloudflared` for Windows (Cloudflare's own installer/MSI).
3. `cloudflared tunnel login` - opens a browser, pick your domain, this
   authorizes the CLI.
4. `cloudflared tunnel create radar` - creates a named, permanent tunnel
   (not a quick tunnel) and prints a tunnel ID.
5. In the Cloudflare Zero Trust dashboard (Networks -> Tunnels -> your
   `radar` tunnel -> Public Hostname), add two public hostnames pointing
   at two different local services **on the same Docker network** (the
   compose file's default network, service DNS names):
   - `radar.yourdomain.com` -> `http://frontend:5173`
   - `api.radar.yourdomain.com` -> `http://backend:8000`

   Using two subdomains (rather than one origin with path-based routing)
   avoids needing a reverse proxy in front of both services - `cloudflared`
   itself routes by hostname.
6. Still in the dashboard, copy this tunnel's **token** (Overview -> Install
   and run connector -> Docker - it hands you a token string directly).
   Put it in `.env` as `CLOUDFLARE_TUNNEL_TOKEN=...`.
7. Set in `.env`:
   ```
   CORS_EXTRA_ORIGINS=https://radar.yourdomain.com
   VITE_API_BASE_URL=https://api.radar.yourdomain.com
   APPROVAL_BASE_URL=https://radar.yourdomain.com
   KAKAO_REDIRECT_URI=https://radar.yourdomain.com/auth/kakao/callback
   ```
   The last two matter for reasons beyond the Android app itself:
   `APPROVAL_BASE_URL` is baked into the approval link sent via KakaoTalk
   (`app/approval/service.py`) - it must be a URL your phone can actually
   open, which `http://localhost:5173` never was even before this Android
   work. Same for `KAKAO_REDIRECT_URI` - if you change it, update the
   matching **Redirect URI** in the Kakao Developers console for this app
   too (see `docs/KAKAO_SETUP.md`), or the OAuth callback will be
   rejected.
8. Rebuild and start with the new values:
   ```
   docker compose build frontend
   docker compose up -d
   docker compose --profile android up -d
   ```
9. Visit `https://radar.yourdomain.com` from your phone's browser. Confirm
   the six tabs load and actually reach the API (not "데이터를 불러오지
   못했습니다." everywhere - if you see that, check `CORS_EXTRA_ORIGINS`/
   `VITE_API_BASE_URL` were both set *before* the `build frontend` step,
   since the API origin only takes effect on rebuild, not restart).

### Step 3 - Confirm the PWA itself works

Before touching Android at all, verify the installable-PWA layer built in
this pass actually works over the real public origin:

- Chrome DevTools -> Application -> Manifest: shows name/icons/
  `display: standalone` correctly, no errors.
- Chrome DevTools -> Application -> Service Workers: shows the worker
  registered and activated.
- Chrome's own install prompt (desktop: an install icon in the address
  bar; Android Chrome: "설치" in the 3-dot menu, or an automatic
  install banner) should appear - if it doesn't, Chrome's install
  criteria aren't met yet (usually a manifest or service-worker issue;
  the DevTools Application panel names the specific failing criterion).
- Optional: run a Lighthouse PWA audit (DevTools -> Lighthouse) against
  the public URL for a full checklist.

### Step 4 - Generate the Android app with Bubblewrap

[Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap) is Google's
own CLI for generating a TWA Android Studio project from a PWA manifest.
Needs Node.js, a JDK, and the Android SDK - Bubblewrap's own installer
can fetch the JDK/SDK for you if you don't already have Android Studio.

```
npm install -g @bubblewrap/cli
bubblewrap init --manifest=https://radar.yourdomain.com/manifest.webmanifest
```

`init` asks a series of questions - accept its defaults pulled from the
manifest for name/icons/colors, and pay attention to:

- **Package name** (e.g. `com.yourname.radar`, reverse-DNS style, chosen
  by you, permanent once published to Play - Google does not allow
  changing it later).
- **Signing key**: let Bubblewrap generate one (`android.keystore`) if you
  don't have one already. **Back this file up somewhere durable and
  memorable the password** - losing it means you can never publish an
  update to the same Play Store listing again, ever; there is no recovery
  process for a lost app-signing key outside Play App Signing (see the
  note on that under Step 6).

This produces an Android Studio project directory with a `twa-manifest.json`
recording your choices.

Build it:

```
bubblewrap build
```

This produces `app-release-signed.apk` (for direct install/testing) and
`app-release-bundle.aab` (the format Play Store submission requires).

### Step 5 - Get the signing certificate's SHA-256 fingerprint

```
keytool -list -v -keystore android.keystore -alias android -storepass <your-password>
```

Copy the `SHA256:` fingerprint line (colon-separated hex).

### Step 6 - Fill in and deploy `assetlinks.json`

Edit `frontend/public/.well-known/assetlinks.json` (already scaffolded,
P43) - replace `REPLACE_WITH_YOUR_PACKAGE_NAME` with the package name
from Step 4 and `REPLACE_WITH_YOUR_SIGNING_CERT_SHA256_FINGERPRINT` with
the fingerprint from Step 5. Commit, rebuild, redeploy:

```
docker compose build frontend
docker compose up -d
```

Verify it's actually served correctly - fetch
`https://radar.yourdomain.com/.well-known/assetlinks.json` directly and
confirm it returns the JSON (not a 404) with `Content-Type:
application/json`. Already confirmed in this pass that `serve` (the
container's static file server, `docker/frontend.Dockerfile`) does serve
this dotfolder correctly out of the box (`200`, correct
`Content-Type: application/json`) - no server change needed here, but
still worth checking your own deployed copy once, since a missing
`assetlinks.json` is the most common reason a TWA falls back to showing a
URL bar. Cross-check with Google's own [Statement List Generator /
verification
tool](https://developers.google.com/digital-asset-links/tools/generator)
for a second opinion.

**Play App Signing note**: if you later publish through the Play Console
and opt into "Play App Signing" (Google re-signs your app with its own
key for distribution, recommended and close to mandatory for new apps),
the fingerprint that actually matters in production becomes Google's
signing key, not yours - the Play Console shows you that fingerprint
under App integrity once you've done your first upload, and
`assetlinks.json` needs updating to that value for the Play-distributed
build to verify. Your own key still matters for direct-install/sideload
testing (Step 7) and as the "upload key" Play re-signs from.

### Step 7 - Test on a real device before anything else

```
adb install app-release-signed.apk
```

(USB debugging enabled on the phone, or transfer the APK and install
manually with unknown-sources allowed.) Open the app. If Digital Asset
Links verified correctly, it opens full-screen with **no browser URL
bar** - that's the whole signal you're looking for. If you instead see a
Custom-Tab-style bar with the URL, verification failed - re-check Step 6
(most common cause), or that `CORS_EXTRA_ORIGINS`/the public origin
itself is reachable from the phone's network.

### Step 8 (optional) - Play Store submission

Only once Step 7 works. Needs a one-time $25 Google Play Console
developer registration, a privacy policy URL (required even for a
personal app if it touches any account data - this app clearly does),
and a content rating questionnaire. Start on a **closed testing** track
(internal or closed, invite-only) rather than production - this is also
where Play App Signing gets opted into on first upload (see the note in
Step 6). Given this project's absolute rule that every real-money action
requires explicit human approval every time, nothing about a Play Store
listing changes that invariant - it's still the same approval-gated app,
just distributed through a different channel.

## Notes / things that will bite you if skipped

- **The service worker caches the app shell aggressively by design**
  (`registerType: 'autoUpdate'`) - after deploying a new frontend build,
  give it a moment (or a manual refresh) to pick up the new version; it
  does not affect API responses (see "Already built" above), only static
  assets.
- **Hash-based routing** (`frontend/src/nav.ts`, `#/positions` etc.)
  works fine inside a TWA - it's just a URL fragment on the same origin,
  no server-side routing involved, nothing Android-specific to configure.
- **Changing the manifest's icons/name later** requires no Bubblewrap
  re-run for anything already installed - Android reads the *live*
  manifest at each TWA launch for some fields, though icon changes may
  need a fresh install to show everywhere (launcher icon caching varies
  by OEM launcher). A full `bubblewrap update && bubblewrap build` is the
  safe way to resync everything, followed by another signed build.
- **`LIVE_TRADING`/`KIS_PAPER_TRADING`/every other safety default stays
  exactly as-is** - none of the Android/TWA wrapping touches trading
  logic. This is purely a distribution/packaging change.
