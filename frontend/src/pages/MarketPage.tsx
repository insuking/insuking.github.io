import { useEffect, useState } from "react";
import { fetchDashboardSummary } from "../api/client";
import type { DashboardSummary } from "../types/dashboard";

const REGIME_LABEL: Record<string, string> = {
  RISK_ON: "위험 선호 (RISK ON)",
  RISK_OFF: "위험 회피 (RISK OFF)",
  NEUTRAL: "중립 (NEUTRAL)",
};

function regimeText(regime: string | null): string {
  if (regime === null) return "데이터 없음 - 아직 충분한 시세 이력이 없습니다";
  return REGIME_LABEL[regime] ?? regime;
}

/** 시장 tab - "is the market safe right now?" in more detail than the
 * home screen's one-line summary. `null` regimes are shown as an honest
 * "no data yet", never a guessed state (see backend/app/api/dashboard.py's
 * module docstring). */
export function MarketPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchDashboardSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
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
        <h1>시장</h1>
      </header>

      {summary === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && <p className="muted">데이터를 불러오지 못했습니다.</p>}

      {summary && (
        <>
          <section className="card">
            <p className="card-title">국내 시장 (KOSPI/KOSDAQ)</p>
            <p className="muted">{regimeText(summary.market_regime)}</p>
          </section>
          <section className="card">
            <p className="card-title">BTC (Upbit KRW-BTC)</p>
            <p className="muted">{regimeText(summary.btc_regime)}</p>
          </section>
        </>
      )}
    </main>
  );
}
