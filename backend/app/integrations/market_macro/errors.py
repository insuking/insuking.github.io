class MarketMacroApiError(RuntimeError):
    """A public Yahoo Finance chart-API call for `symbol` failed or
    returned data this client can't use (a reported API error, an empty
    result, or missing/unusable price fields)."""

    def __init__(self, symbol: str, status_code: int | None, reason: str) -> None:
        self.symbol = symbol
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"Market macro API error for {symbol} ({status_code}): {reason}")
