class KisNotConfiguredError(RuntimeError):
    """Raised when KIS_APP_KEY/KIS_APP_SECRET are not set.

    Callers must catch this and surface a BLOCKED status - never fall back to
    mocked data outside a unit test (docs/MASTER_SPEC.md P3 acceptance).
    """


class KisAuthError(RuntimeError):
    """The KIS auth endpoint rejected our credentials or returned no token."""


class KisApiError(RuntimeError):
    """A KIS REST call returned a non-success rt_cd."""
