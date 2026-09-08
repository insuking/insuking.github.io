import { useEffect, useState } from "react";
import { fetchPerformance } from "../api/client";
import type { DashboardPerformance, PerformanceSummary } from "../types/dashboard";

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

function pnlClass(value: number): string {
  if (value > 0) return "pnl-gain";
  if (value < 0) return "pnl-loss";
  return "pnl-flat";
}

function formatPnl(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${numberFormatter.format(value)}`;
}

function PerformanceCard({ title, summary }: { title: string; summary: PerformanceSummary }) {
  const winRate = summary.trade_count > 0 ? (summary.win_count / summary.trade_count) * 100 : null;
  return (
    <section className="card">
      <p className="card-title">{title}</p>
      <div className="card-row">
        <span>실현손익</span>
        <span className={pnlClass(summary.realized_pnl)}>{formatPnl(summary.realized_pnl)}</span>
      </div>
      <div className="card-row">
        <span>거래 수</span>
        <span>{summary.trade_count}</span>
      </div>
      <div className="card-row">
        <span>승/패</span>
        <span>
          {summary.win_count} / {summary.loss_count}
        </span>
      </div>
      <div className="card-row">
        <span>승률</span>
        <span className="muted">{winRate === null ? "—" : `${winRate.toFixed(0)}%`}</span>
      </div>
    </section>
  );
}

/** 성과 tab - real and paper PnL are always shown as two separate cards,
 * never blended into one number (see backend/app/api/dashboard.py's
 * `DashboardPerformance` docstring for why). */
export function PerformancePage() {
  const [performance, setPerformance] = useState<DashboardPerformance | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchPerformance()
      .then((data) => {
        if (!cancelled) setPerformance(data);
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
        <h1>성과</h1>
      </header>

      {performance === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && <p className="muted">데이터를 불러오지 못했습니다.</p>}

      {performance && (
        <>
          <PerformanceCard title="실전 거래" summary={performance.real} />
          <PerformanceCard title="페이퍼 거래" summary={performance.paper} />
        </>
      )}
    </main>
  );
}
