"""KakaoTalk 'send to me' notification (P12).

Sends the human-approval link to the logged-in user's own KakaoTalk via the
memo/default/send API - the P13 approval flow calls this to deliver an
actionable message, but per docs/MASTER_SPEC.md's Kakao fallback rule, a
notification failure must never block the trading engine: `Approval` rows
(see app/db/models.py, P2) exist and are visible in-app regardless of
whether this send succeeds, so callers must catch `KakaoNotificationError`
and continue rather than let it propagate into the approval-creation path.

Endpoint verified via web-search snippets of Kakao's own docs (direct fetch
to developers.kakao.com is blocked, as in auth.py): `POST
https://kapi.kakao.com/v2/api/talk/memo/default/send`, Bearer-authenticated,
form-encoded body with a `template_object` field holding a JSON-encoded
message template; success is `HTTP 200` with body `{"result_code": 0}`
(confirmed directly from Kakao's own "REST API" reference page for this
endpoint), failure returns a non-zero `result_code` or a Kakao-standard
`{"code": ..., "msg": ...}` error envelope. Requires the `talk_message`
consent scope granted during Kakao Login (P12's auth.py does not itself
verify this scope was granted - Kakao's own API is the source of truth and
returns an error here if it wasn't).
"""

from __future__ import annotations

import json

import httpx

from app.core.config import Settings, get_settings
from app.integrations.kakao.errors import KakaoNotConfiguredError, KakaoNotificationError

_MEMO_SEND_PATH = "/v2/api/talk/memo/default/send"


class KakaoNotifier:
    def __init__(self, client: httpx.AsyncClient, settings: Settings | None = None) -> None:
        self._client = client
        self.settings = settings or get_settings()

    async def send_approval_link(self, access_token: str, approval_url: str, message: str) -> None:
        """Send a text message with a button linking to `approval_url`."""
        if not self.settings.kakao_configured:
            raise KakaoNotConfiguredError(
                "KAKAO_CLIENT_ID / KAKAO_REDIRECT_URI are not set - see docs/KAKAO_SETUP.md"
            )

        template_object = {
            "object_type": "text",
            "text": message,
            "link": {"web_url": approval_url, "mobile_web_url": approval_url},
            "button_title": "승인하기",  # "승인하기" (Approve)
        }
        response = await self._client.post(
            f"{self.settings.kakao_api_base_url}{_MEMO_SEND_PATH}",
            data={"template_object": json.dumps(template_object)},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        result_code = body.get("result_code") if isinstance(body, dict) else None

        # A 200 status alone isn't Kakao's success signal for this endpoint -
        # `result_code == 0` is (see module docstring) - so both are checked
        # rather than trusting the HTTP status to mean delivery succeeded.
        if response.status_code != 200 or result_code != 0:
            raise KakaoNotificationError(f"Kakao notification send failed: {response.status_code} {body}")
