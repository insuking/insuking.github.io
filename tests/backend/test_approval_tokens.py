import pytest

from app.approval.tokens import generate_token, hash_token

pytestmark = pytest.mark.P13


def test_generate_token_returns_plaintext_and_matching_hash() -> None:
    plaintext, digest = generate_token()

    assert plaintext
    assert digest == hash_token(plaintext)


def test_generate_token_is_unique_each_call() -> None:
    plaintext1, digest1 = generate_token()
    plaintext2, digest2 = generate_token()

    assert plaintext1 != plaintext2
    assert digest1 != digest2


def test_hash_token_is_deterministic() -> None:
    assert hash_token("same-input") == hash_token("same-input")


def test_hash_token_differs_for_different_input() -> None:
    assert hash_token("a") != hash_token("b")
