# Kakao Login + Notification Setup (placeholder)

This guide will be filled in during **P12 (Kakao Login + Notification)**. It will
cover:

- Creating a Kakao Developers application
- Registering redirect URIs for Kakao Login (OAuth)
- Requesting the `talk_message` consent item for "send to me" notifications
- Server-side REST call to send an approval-link message to the logged-in user's
  own KakaoTalk chat
- Token storage and refresh (official Kakao refresh mechanism only)

Until this phase lands, no Kakao integration exists in the codebase. Any
notification failure must never block the trading engine (see master spec,
section "KAKAO FALLBACK") — Pending Approvals will remain visible inside the
app UI regardless of notification delivery status.
