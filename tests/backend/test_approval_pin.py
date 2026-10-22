import pytest

from app.approval.errors import PinIncorrectError, PinNotConfiguredError
from app.approval.pin import hash_pin, verify_pin
from app.core.config import Settings

pytestmark = pytest.mark.P13


def _settings_with_pin(pin: str) -> Settings:
    return Settings(app_pin_hash=hash_pin(pin))  # type: ignore[arg-type]


def test_hash_pin_is_deterministic_with_fixed_salt() -> None:
    salt = b"0123456789abcdef"
    assert hash_pin("1234", salt=salt) == hash_pin("1234", salt=salt)


def test_hash_pin_differs_with_random_salt() -> None:
    assert hash_pin("1234") != hash_pin("1234")


def test_verify_pin_succeeds_for_correct_pin() -> None:
    settings = _settings_with_pin("4821")
    verify_pin("4821", settings)  # must not raise


def test_verify_pin_raises_for_incorrect_pin() -> None:
    settings = _settings_with_pin("4821")
    with pytest.raises(PinIncorrectError):
        verify_pin("0000", settings)


def test_verify_pin_raises_when_not_configured() -> None:
    settings = Settings(app_pin_hash="")  # type: ignore[arg-type]
    with pytest.raises(PinNotConfiguredError):
        verify_pin("4821", settings)


def test_verify_pin_raises_when_malformed() -> None:
    settings = Settings(app_pin_hash="not-a-valid-hash")  # type: ignore[arg-type]
    with pytest.raises(PinNotConfiguredError):
        verify_pin("4821", settings)
