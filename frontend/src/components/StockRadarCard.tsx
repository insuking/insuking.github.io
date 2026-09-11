import type { StockRadarCandidate } from "../types/stockRadar";
import "./StockRadarCard.css";

interface StockRadarCardProps {
  candidate: StockRadarCandidate;
}

/**
 * One PRE-BREAKOUT candidate (P23/P25) from the stock radar tab. Unlike
 * `RecommendationCard`, there's no entry/stop/target here - a radar score
 * is a ranking signal, not yet an actionable trade plan (see
 * `app/recommendation/engine.py`'s docstring on why ranking, recommendation,
 * and approval stay three separate steps). `max_available` is always shown
 * next to `total_score`, never a bare number out of an assumed 100 - see
 * `app/stock_radar/scoring.py`'s own module docstring for why that
 * denominator moves (65/77 depending on whether investor-flow data was
 * available for this symbol).
 */
export function StockRadarCard({ candidate }: StockRadarCardProps) {
  const label = candidate.name ? `${candidate.symbol} (${candidate.name})` : candidate.symbol;

  return (
    <article className="stock-card" data-testid="stock-radar-card">
      <header className="stock-card__header">
        <div>
          {candidate.rank !== null && <span className="stock-card__rank">#{candidate.rank}</span>}
          <span className="stock-card__symbol">{label}</span>
        </div>
        <span className="stock-card__score">
          {Math.round(candidate.total_score)} / {Math.round(candidate.max_available)}
        </span>
      </header>

      {candidate.positive.length > 0 && (
        <ul className="stock-card__factors stock-card__factors--positive">
          {candidate.positive.map((factor) => (
            <li key={factor.factor}>{factor.detail}</li>
          ))}
        </ul>
      )}

      {candidate.negative.length > 0 && (
        <ul className="stock-card__factors stock-card__factors--negative">
          {candidate.negative.map((factor) => (
            <li key={factor.factor}>{factor.detail}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
