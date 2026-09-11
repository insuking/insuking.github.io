/**
 * Stock radar (P23/P25/P26/P27/P28) - TypeScript mirror of the Pydantic
 * response models in backend/app/api/stock_radar.py.
 */

export interface ScoreFactor {
  factor: string;
  points: number;
  detail: string;
}

export interface StockRadarCandidate {
  symbol: string;
  name: string | null;
  market: string | null;
  rank: number | null;
  total_score: number;
  max_available: number;
  positive: ScoreFactor[];
  negative: ScoreFactor[];
}

export interface StockRadarLatest {
  scan_run_id: string | null;
  scored_at: string | null;
  candidates: StockRadarCandidate[];
}
