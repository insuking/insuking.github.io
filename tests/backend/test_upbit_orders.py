"""Unit tests for the Upbit authenticated order client (mocked transport -
never a real Upbit connection)."""

import httpx
import pytest

from app.integrations.upbit.auth import UpbitAuth
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.orders import UpbitOrderClient

pytestmark = pytest.mark.P15


def _client_with(handler) -> tuple[httpx.AsyncClient, UpbitOrderClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.upbit.test")
    order_client = UpbitOrderClient(client, UpbitAuth("access-1", "secret-1"))
    return client, order_client


@pytest.mark.asyncio
async def test_place_order_posts_body_and_bearer_header() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(201, json={"uuid": "order-uuid-1", "state": "wait"})

    _client, orders = _client_with(handler)
    result = await orders.place_order(market="KRW-BTC", side="bid", ord_type="limit", volume="1", price="1000")

    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/orders"
    assert request.headers["Authorization"].startswith("Bearer ")
    import json

    body = json.loads(request.content)
    assert body == {"market": "KRW-BTC", "side": "bid", "ord_type": "limit", "volume": "1", "price": "1000"}
    assert result == {"uuid": "order-uuid-1", "state": "wait"}


@pytest.mark.asyncio
async def test_cancel_order_sends_uuid_as_query_param() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"uuid": "order-uuid-1", "state": "cancel"})

    _client, orders = _client_with(handler)
    result = await orders.cancel_order("order-uuid-1")

    request = seen_requests[0]
    assert request.method == "DELETE"
    assert request.url.path == "/v1/order"
    assert dict(request.url.params) == {"uuid": "order-uuid-1"}
    assert result == {"uuid": "order-uuid-1", "state": "cancel"}


@pytest.mark.asyncio
async def test_get_order_sends_uuid_as_query_param() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"uuid": "order-uuid-1", "state": "done"})

    _client, orders = _client_with(handler)
    result = await orders.get_order("order-uuid-1")

    request = seen_requests[0]
    assert request.method == "GET"
    assert request.url.path == "/v1/order"
    assert dict(request.url.params) == {"uuid": "order-uuid-1"}
    assert result == {"uuid": "order-uuid-1", "state": "done"}


@pytest.mark.asyncio
async def test_list_orders_sends_expected_query_params() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json=[{"uuid": "order-uuid-1"}])

    _client, orders = _client_with(handler)
    result = await orders.list_orders(market="KRW-BTC", state="wait")

    request = seen_requests[0]
    assert dict(request.url.params) == {
        "market": "KRW-BTC",
        "state": "wait",
        "page": "1",
        "limit": "100",
        "order_by": "desc",
    }
    assert result == [{"uuid": "order-uuid-1"}]


@pytest.mark.asyncio
async def test_list_orders_returns_empty_list_for_non_list_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "unexpected"})

    _client, orders = _client_with(handler)
    result = await orders.list_orders(market="KRW-BTC")

    assert result == []


@pytest.mark.asyncio
async def test_place_order_raises_on_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"name": "invalid_query", "message": "bad params"}})

    _client, orders = _client_with(handler)

    with pytest.raises(UpbitApiError) as exc_info:
        await orders.place_order(market="KRW-BTC", side="bid", ord_type="limit", volume="1", price="1000")

    assert exc_info.value.status_code == 400
    assert exc_info.value.name == "invalid_query"
    assert exc_info.value.message == "bad params"
