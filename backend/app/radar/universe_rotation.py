"""P39 (extends P30): deterministic round-robin chunk selection so a
rate-limited full-universe scan actually covers every tradable symbol
over successive runs, instead of only ever scanning the same top-N by
liquidity and never touching the rest of the market.

`scripts/scan_stocks.py`'s `_full_universe_symbols()` used to cap the
real KOSPI+KOSDAQ universe (`app/integrations/kis/krx_master.py`) at a
fixed top-N-by-liquidity per market and scan exactly that same slice
every single run - the other several thousand symbols were never
scanned, ever, no matter how long the deployment ran. This module fixes
that: given the *entire* tradable universe (already ordered, most liquid
first) and a chunk size, it picks one chunk per call, advancing through
every chunk in order and wrapping back to the start as time passes - so
every tradable symbol eventually gets scanned, just not all in the same
pass, since KIS's confirmed ~2 req/sec rate limit makes scanning several
thousand symbols in one run take well over an hour.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TypeVar

T = TypeVar("T")


def select_rotation_chunk(  # noqa: UP047 - runtime is Python 3.11, PEP 695 generics need 3.12
    items: list[T], chunk_size: int, now: datetime, interval_seconds: int
) -> list[T]:
    """Returns one `chunk_size`-sized slice of `items`, chosen
    deterministically from `now` and `interval_seconds` - no persisted
    "last chunk scanned" state needed, since the chunk index is derived
    purely from wall-clock time divided into `interval_seconds`-wide
    slots. Calls roughly `interval_seconds` apart (matching the caller's
    own run cadence, e.g. `SCHEDULER_STOCK_INTERVAL_SECONDS`) land in
    successive slots and so advance through every chunk in order,
    wrapping back to the first chunk once the last one is reached.

    `items` should already be in the priority order chunks should be
    scanned in (e.g. by liquidity, most important first) - that only
    affects which symbols get scanned more *recently* at any given
    moment, never which symbols get scanned at all; every item is still
    covered eventually regardless of order.
    """
    if not items or chunk_size <= 0 or interval_seconds <= 0:
        return []
    num_chunks = math.ceil(len(items) / chunk_size)
    slot = int(now.timestamp() // interval_seconds)
    chunk_index = slot % num_chunks
    start = chunk_index * chunk_size
    return items[start : start + chunk_size]
