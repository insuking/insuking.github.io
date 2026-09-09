import { useEffect, useState } from "react";
import { fetchStockRadarLatest } from "../api/client";
import { StockRadarCard } from "../components/StockRadarCard";
import type { StockRadarLatest } from "../types/stockRadar";

/**
 * 종목레이더 tab (P28) - the KOSPI/KOSDAQ PRE-BREAKOUT candidate list from
 * `scripts/scan_stocks.py`'s most recent real scan (P23/P25/P26), read via
 * `/api/stock-radar/latest`. Deliberately its own tab rather than folded
 * into the existing "추천" tab: a radar candidate here is a ranking signal
 * (`PreBreakoutScore`), not the entry/stop/target `Recommendation` that
 * tab shows - conflating the two would misrepresent a score as an
 * actionable trade plan before P29's KIS order service exists.
 */
export function StockRadarPage() {
  const [data, setData] = useState<StockRadarLatest | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchStockRadarLatest()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="page">
      <header className="app-header">
        <h1>종목레이더</h1>
      </header>

      {data === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && <p className="muted">데이터를 불러오지 못했습니다.</p>}

      {data && data.candidates.length === 0 && (
        <section className="card">
          <p className="muted">아직 스캔 결과가 없습니다. scripts/scan_stocks.py를 먼저 실행하세요.</p>
        </section>
      )}

      {data?.candidates.map((candidate) => (
        <StockRadarCard key={candidate.symbol} candidate={candidate} />
      ))}
    </main>
  );
}
