"""P30 acceptance: real connection to the KRX master-file download host, no
mocking.

`new.real.download.dws.co.kr` needs no API key (it's a plain static file
server, unrelated to KIS's authenticated REST API), so unlike
test_kis_integration.py this can't skip on "not configured" - it skips
instead on a real network-level failure making the connection, matching
test_upbit_integration.py's pattern: this sandbox's egress policy denies
the CONNECT outright (confirmed directly with `curl`, which the proxy
rejected with a 403 - see app/integrations/kis/krx_master.py's own
docstring). Only the connection *attempt* is allowed to turn into a skip;
a real connection that then fails to parse would be an actual bug.
"""

import httpx
import pytest
from app.integrations.kis.krx_master import KOSPI_MASTER_URL, fetch_kospi_master

pytestmark = [pytest.mark.P30, pytest.mark.asyncio]


async def test_real_kospi_master_download_and_parse() -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(KOSPI_MASTER_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            pytest.skip(
                f"could not reach the KRX master-file host from this sandbox "
                f"(network egress blocked): {type(exc).__name__}: {exc}"
            )
            return

        rows = await fetch_kospi_master(client)
        assert len(rows) > 100  # the real KOSPI universe is well over 100 symbols
        assert any(r.symbol == "005930" for r in rows)  # 삼성전자 - always listed
