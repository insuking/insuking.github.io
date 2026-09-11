import { useMemo, useState } from "react";
import { fetchStockRadarLatest } from "../api/client";
import { StockRadarCard } from "../components/StockRadarCard";
import type { StockRadarLatest } from "../types/stockRadar";
import { usePolledFetch } from "../hooks/usePolledFetch";

const STOCK_RADAR_POLL_MS = 60_000;

type MarketFilter = "ALL" | "KOSPI" | "KOSDAQ";

function freshnessText(scoredAt: string | null): string | null {
  if (scoredAt === null) return null;
  const scored = new Date(scoredAt);
  if (Number.isNaN(scored.getTime())) return null;
  const minutesAgo = Math.max(0, Math.round((Date.now() - scored.getTime()) / 60000));
  if (minutesAgo < 1) return "방금 스캔됨";
  if (minutesAgo < 60) return `${minutesAgo}분 전 스캔`;
  const hoursAgo = Math.round(minutesAgo / 60);
  return `${hoursAgo}시간 전 스캔`;
}

/**
 * 종목레이더 tab (P28, extended in P42) - the KOSPI/KOSDAQ PRE-BREAKOUT
 * candidate list from `scripts/scan_stocks.py`'s most recent real scan
 * (P23/P25/P26), read via `/api/stock-radar/latest`. Deliberately its own
 * tab rather than folded into the existing "추천" tab: a radar candidate
 * here is a ranking signal (`PreBreakoutScore`), not the entry/stop/target
 * `Recommendation` that tab shows - conflating the two would misrepresent
 * a score as an actionable trade plan before P29's KIS order service
 * exists. P42 adds a scan-freshness readout (so a stale scan is obvious,
 * not silently shown as current) and a KOSPI/KOSDAQ filter, on top of the
 * auto-refresh/retry every page now gets.
 */
export function StockRadarPage() {
  const {
    data,
    error: loadError,
    refetch,
  } = usePolledFetch<StockRadarLatest>(fetchStockRadarLatest, STOCK_RADAR_POLL_MS);
  const [marketFilter, setMarketFilter] = useState<MarketFilter>("ALL");

  const candidates = useMemo(() => {
    if (!data) return [];
    if (marketFilter === "ALL") return data.candidates;
    return data.candidates.filter((c) => c.market === marketFilter);
  }, [data, marketFilter]);

  const freshness = data ? freshnessText(data.scored_at) : null;

  return (
    <main className="page">
      <header className="app-header">
        <h1>종목레이더</h1>
      </header>

      {freshness && <p className="muted small">{freshness}</p>}

      {data && data.candidates.length > 0 && (
        <div className="filter-chips">
          {(["ALL", "KOSPI", "KOSDAQ"] as const).map((market) => (
            <button
              key={market}
              type="button"
              className={`filter-chip${marketFilter === market ? " filter-chip--active" : ""}`}
              onClick={() => setMarketFilter(market)}
            >
              {market === "ALL" ? "전체" : market}
            </button>
          ))}
        </div>
      )}

      {data === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && (
        <section className="card">
          <p className="muted">데이터를 불러오지 못했습니다.</p>
          <button type="button" className="retry-button" onClick={refetch}>
            다시 시도
          </button>
        </section>
      )}

      {data && data.candidates.length === 0 && (
        <section className="card">
          <p className="muted">아직 스캔 결과가 없습니다. scripts/scan_stocks.py를 먼저 실행하세요.</p>
        </section>
      )}

      {data && data.candidates.length > 0 && candidates.length === 0 && (
        <section className="card">
          <p className="muted">해당 시장의 후보가 없습니다.</p>
        </section>
      )}

      {candidates.map((candidate) => (
        <StockRadarCard key={candidate.symbol} candidate={candidate} />
      ))}
    </main>
  );
}
