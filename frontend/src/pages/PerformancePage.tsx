import { fetchPerformance } from "../api/client";
import type { DashboardPerformance, PerformanceSummary } from "../types/dashboard";
import { usePolledFetch } from "../hooks/usePolledFetch";

const PERFORMANCE_POLL_MS = 60_000;

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

/** 성과 tab (extended in P42) - real and paper PnL are always shown as
 * two separate cards, never blended into one number (see
 * backend/app/api/dashboard.py's `DashboardPerformance` docstring for
 * why). Auto-refreshes every 60s with a retry button on failure. */
export function PerformancePage() {
  const {
    data: performance,
    error: loadError,
    refetch,
  } = usePolledFetch<DashboardPerformance>(fetchPerformance, PERFORMANCE_POLL_MS);

  return (
    <main className="page">
      <header className="app-header">
        <h1>성과</h1>
      </header>

      {performance === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && (
        <section className="card">
          <p className="muted">데이터를 불러오지 못했습니다.</p>
          <button type="button" className="retry-button" onClick={refetch}>
            다시 시도
          </button>
        </section>
      )}

      {performance && (
        <>
          <PerformanceCard title="실전 거래" summary={performance.real} />
          <PerformanceCard title="페이퍼 거래" summary={performance.paper} />
          <section className="card">
            <p className="card-title">위험 회피 실적 (최근 {performance.risk_avoidance.window_days}일)</p>
            <div className="card-row">
              <span>과열 진입 차단 (TOO LATE)</span>
              <span>{performance.risk_avoidance.too_late_excluded_count}건</span>
            </div>
            <div className="card-row">
              <span>무리한 매수 대신 관망한 날</span>
              <span>{performance.risk_avoidance.no_trade_day_count}일</span>
            </div>
            <p className="muted small">
              승률/손익과 별개로, 시스템이 실제로 위험한 진입을 걸러낸 횟수입니다. 정식 백테스트 기반 회피율
              KPI는 아직 준비 중입니다.
            </p>
          </section>
        </>
      )}
    </main>
  );
}
