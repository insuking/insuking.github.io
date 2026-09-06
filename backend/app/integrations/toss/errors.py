class TossNotConfiguredError(RuntimeError):
    """Raised when TOSS_CLIENT_ID/TOSS_CLIENT_SECRET are not set.

    Callers must surface a BLOCKED status - never fall back to mocked data
    outside a unit test (docs/MASTER_SPEC.md P5 acceptance).
    """


class TossAuthError(RuntimeError):
    """The Toss OAuth2 token endpoint rejected our credentials."""


class TossApiError(RuntimeError):
    """A Toss REST call returned a non-2xx response.

    Mirrors the error envelope Toss's own client library documents: a code
    and message pulled from whichever of `error.code`/`code`/`error` and
    `error.message`/`message`/`error_description` the response body has.
    """

    def __init__(
        self,
        status_code: int,
        code: str | None,
        message: str | None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"Toss API error {status_code} ({code}): {message} [request_id={request_id}]")


class TossRateLimitError(TossApiError):
    """HTTP 429 specifically - callers may retry after backing off."""
