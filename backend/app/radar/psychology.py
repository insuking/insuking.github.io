"""Crowd-psychology signals (P11).

Pure functions over a `Candle` series / a single price level, same style and
constraints as `app.radar.smart_money`. Per docs/MASTER_SPEC.md P11, these
describe observable statistical patterns in price and volume that are
*consistent with* common retail behavioral biases (FOMO, chasing, anchoring,
exhaustion) - never a claim about what any individual trader felt or
intended.
"""

from __future__ import annotations

from app.models.domain import Candle
from app.radar.smart_money import buy_aggression_ratio


def fomo_score(candles: list[Candle], window: int = 5) -> float:
    """0-100: price acceleration paired with expanding volume.

    Compares the return and average volume of the trailing `window` bars
    against the `window` bars before that. A bigger, faster move on more
    volume than the move that preceded it is the price/volume signature
    commonly associated with retail FOMO buying chasing a breakout.
    """
    if len(candles) < 2 * window:
        return 0.0

    recent = candles[-window:]
    prior = candles[-2 * window : -window]

    recent_return = (recent[-1].close - recent[0].close) / recent[0].close if recent[0].close else 0.0
    prior_return = (prior[-1].close - prior[0].close) / prior[0].close if prior[0].close else 0.0
    acceleration = recent_return - prior_return

    recent_avg_volume = sum(c.volume for c in recent) / len(recent)
    prior_avg_volume = sum(c.volume for c in prior) / len(prior)
    volume_expansion = recent_avg_volume / prior_avg_volume if prior_avg_volume > 0 else 1.0

    score = 0.0
    score += max(0.0, min(acceleration * 200.0, 60.0))
    score += max(0.0, min((volume_expansion - 1.0) * 20.0, 40.0))
    return max(0.0, min(100.0, score))


def chasing_score(candles: list[Candle], breakout_level: float, window: int = 10) -> float:
    """0-100: how far price has already run past `breakout_level` while
    buy-side aggression (see `buy_aggression_ratio`) is still elevated - a
    proxy for entries chasing an already-extended move rather than the
    original breakout.
    """
    if not candles or breakout_level <= 0:
        return 0.0

    latest = candles[-1]
    extension = max(0.0, (latest.close - breakout_level) / breakout_level)
    aggression = max(0.0, buy_aggression_ratio(candles, window))

    score = min(extension * 100.0, 70.0) + aggression * 30.0
    return max(0.0, min(100.0, score))


def round_number_proximity(price: float, step: float = 1000.0) -> float:
    """0.0-1.0: how close `price` sits to the nearest multiple of `step`.

    1.0 exactly on a round number, 0.0 exactly halfway between two round
    numbers - a simple model of the anchoring bias that clusters orders
    around round price levels (e.g. KRW 10,000 rungs).
    """
    if price <= 0 or step <= 0:
        return 0.0
    remainder = price % step
    distance = min(remainder, step - remainder)
    return max(0.0, 1.0 - distance / (step / 2))


def crowd_exhaustion_score(candles: list[Candle], window: int = 10) -> float:
    """0-100: a fresh high made on declining volume within the window.

    Splits the trailing `window` bars in half; if the latest bar set the
    window's high, the score is how much the second half's average volume
    fell short of the first half's - a classic bearish volume/price
    divergence suggesting buying interest is fading even as price still
    pushes higher. 0.0 when the latest bar isn't a fresh high at all.
    """
    if len(candles) < window or window < 2:
        return 0.0

    recent = candles[-window:]
    if recent[-1].high < max(c.high for c in recent):
        return 0.0

    midpoint = window // 2
    first_half = recent[:midpoint]
    second_half = recent[midpoint:]
    first_avg_volume = sum(c.volume for c in first_half) / len(first_half)
    second_avg_volume = sum(c.volume for c in second_half) / len(second_half)
    if first_avg_volume <= 0:
        return 0.0

    decline = max(0.0, (first_avg_volume - second_avg_volume) / first_avg_volume)
    return max(0.0, min(100.0, decline * 100.0))
