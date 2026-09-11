"""Unit tests for Upbit JWT request signing - verified against
sharebook-kr/pyupbit's `_request_headers()` (see auth.py's module
docstring). No network calls; this only checks the JWT this module builds
decodes back to the expected claims and hash.
"""

import hashlib
from urllib.parse import urlencode

import jwt
import pytest

from app.integrations.upbit.auth import UpbitAuth

pytestmark = pytest.mark.P15


def _decode(token: str, secret: str) -> dict[str, object]:
    return jwt.decode(token, secret, algorithms=["HS256"])


def test_build_headers_without_params_omits_query_hash() -> None:
    auth = UpbitAuth("access-key-1", "secret-key-1")
    headers = auth.build_headers()

    token = headers["Authorization"].removeprefix("Bearer ")
    claims = _decode(token, "secret-key-1")

    assert claims["access_key"] == "access-key-1"
    assert "nonce" in claims
    assert "query_hash" not in claims
    assert "query_hash_alg" not in claims


def test_build_headers_with_params_includes_matching_query_hash() -> None:
    auth = UpbitAuth("access-key-1", "secret-key-1")
    params = {"market": "KRW-BTC", "side": "bid", "volume": "1", "price": "1000", "ord_type": "limit"}
    headers = auth.build_headers(params)

    token = headers["Authorization"].removeprefix("Bearer ")
    claims = _decode(token, "secret-key-1")

    expected_encoded = urlencode(params, doseq=True).replace("%5B%5D=", "[]=")
    expected_hash = hashlib.sha512(expected_encoded.encode()).hexdigest()

    assert claims["query_hash"] == expected_hash
    assert claims["query_hash_alg"] == "SHA512"


def test_build_headers_generates_a_fresh_nonce_each_call() -> None:
    auth = UpbitAuth("access-key-1", "secret-key-1")
    token1 = auth.build_headers()["Authorization"].removeprefix("Bearer ")
    token2 = auth.build_headers()["Authorization"].removeprefix("Bearer ")

    claims1 = _decode(token1, "secret-key-1")
    claims2 = _decode(token2, "secret-key-1")

    assert claims1["nonce"] != claims2["nonce"]


def test_build_headers_signature_is_invalid_with_wrong_secret() -> None:
    auth = UpbitAuth("access-key-1", "secret-key-1")
    token = auth.build_headers()["Authorization"].removeprefix("Bearer ")

    with pytest.raises(jwt.InvalidSignatureError):
        _decode(token, "wrong-secret")
