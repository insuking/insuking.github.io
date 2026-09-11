class UpbitApiError(RuntimeError):
    """A public Upbit REST call returned a non-2xx response."""

    def __init__(self, status_code: int, name: str | None, message: str | None) -> None:
        self.status_code = status_code
        self.name = name
        self.message = message
        super().__init__(f"Upbit API error {status_code} ({name}): {message}")
