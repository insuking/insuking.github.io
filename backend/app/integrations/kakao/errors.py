class KakaoNotConfiguredError(RuntimeError):
    """Raised when KAKAO_CLIENT_ID/KAKAO_REDIRECT_URI are not set.

    Callers must surface a BLOCKED status - never fall back to mocked data
    outside a unit test (docs/MASTER_SPEC.md P12 acceptance: "official APIs
    only, no faked success").
    """


class KakaoAuthError(RuntimeError):
    """The Kakao OAuth2 token endpoint, or the user-info endpoint, rejected
    the request (bad code/refresh_token, expired token, revoked consent)."""


class KakaoNotificationError(RuntimeError):
    """The KakaoTalk 'send to me' memo API call failed or was not delivered.

    Per docs/MASTER_SPEC.md's Kakao fallback rule, callers must catch this
    and continue - a failed notification must never block an approval from
    existing or being visible in-app; it only means the KakaoTalk ping
    didn't go out.
    """
