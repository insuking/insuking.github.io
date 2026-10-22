import { fetchDashboardSummary } from "../api/client";
import type { DashboardSummary } from "../types/dashboard";
import { usePolledFetch } from "../hooks/usePolledFetch";

const MARKET_POLL_MS = 60_000;

const REGIME_LABEL: Record<string, string> = {
  RISK_ON: "위험 선호 (RISK ON)",
  RISK_OFF: "위험 회피 (RISK OFF)",
  NEUTRAL: "중립 (NEUTRAL)",
};

const DECISION_LABEL: Record<string, string> = {
  STRONG_BUY: "적극 매수 후보",
  BUY: "매수 후보",
  WATCH: "관망",
  NO_BUY: "매수 보류",
  NO_TRADE_DAY: "오늘은 거래 없음",
};

function regimeText(regime: string | null): string {
  if (regime === null) return "데이터 없음 - 아직 충분한 시세 이력이 없습니다";
  return REGIME_LABEL[regime] ?? regime;
}

function freshnessText(updatedAt: string | null): string | null {
  if (updatedAt === null) return null;
  const updated = new Date(updatedAt);
  if (Number.isNaN(updated.getTime())) return null;
  const minutesAgo = Math.max(0, Math.round((Date.now() - updated.getTime()) / 60000));
  if (minutesAgo < 1) return "방금 갱신됨";
  if (minutesAgo < 60) return `${minutesAgo}분 전 갱신`;
  const hoursAgo = Math.round(minutesAgo / 60);
  return `${hoursAgo}시간 전 갱신`;
}

/** 시장 tab (extended in P42) - "is the market safe right now?" in more
 * detail than the home screen's one-line summary. `null` regimes are
 * shown as an honest "no data yet", never a guessed state (see
 * backend/app/api/dashboard.py's module docstring). Auto-refreshes every
 * 60s with a retry button on failure. */
export function MarketPage() {
  const {
    data: summary,
    error: loadError,
    refetch,
  } = usePolledFetch<DashboardSummary>(fetchDashboardSummary, MARKET_POLL_MS);

  return (
    <main className="page">
      <header className="app-header">
        <h1>시장</h1>
      </header>

      {summary === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && (
        <section className="card">
          <p className="muted">데이터를 불러오지 못했습니다.</p>
          <button type="button" className="retry-button" onClick={refetch}>
            다시 시도
          </button>
        </section>
      )}

      {summary && (
        <>
          <section className="card">
            <p className="card-title">국내 시장 (KOSPI/KOSDAQ)</p>
            <p className="muted">{regimeText(summary.market_regime)}</p>
            {freshnessText(summary.market_regime_updated_at) && (
              <p className="muted small">{freshnessText(summary.market_regime_updated_at)}</p>
            )}
          </section>
          <section className="card">
            <p className="card-title">BTC (Upbit KRW-BTC)</p>
            <p className="muted">{regimeText(summary.btc_regime)}</p>
            {freshnessText(summary.btc_regime_updated_at) && (
              <p className="muted small">{freshnessText(summary.btc_regime_updated_at)}</p>
            )}
          </section>
          <section className="card">
            <p className="card-title">해외 매크로 (프리마켓 체크)</p>
            {summary.macro_regime === null ? (
              <p className="muted">아직 오늘의 매크로 체크 결과가 없습니다 (매일 08:20 KST 실행).</p>
            ) : (
              <>
                <p className="muted">{REGIME_LABEL[summary.macro_regime] ?? summary.macro_regime}</p>
                {summary.macro_headline && <p className="muted small">{summary.macro_headline}</p>}
                {freshnessText(summary.macro_observed_at) && (
                  <p className="muted small">{freshnessText(summary.macro_observed_at)}</p>
                )}
                <p className="muted small">
                  참고용 신호입니다 - 이 값만으로 자동 매매 여부가 결정되지 않으며, 매수/매도는 항상 사람의
                  승인이 필요합니다.
                </p>
              </>
            )}
          </section>
          <section className="card">
            <p className="card-title">오늘의 판정</p>
            {summary.stock_decision_state === null ? (
              <p className="muted">아직 오늘의 재확인 스캔 결과가 없습니다.</p>
            ) : (
              <>
                <p className="muted">{DECISION_LABEL[summary.stock_decision_state] ?? summary.stock_decision_state}</p>
                {summary.stock_decision_top_symbol_name && (
                  <div className="card-row">
                    <span>최상위 후보</span>
                    <span>
                      {summary.stock_decision_top_symbol_name} ({summary.stock_decision_top_symbol})
                    </span>
                  </div>
                )}
                {summary.stock_decision_reason && <p className="muted small">{summary.stock_decision_reason}</p>}
                {freshnessText(summary.stock_decision_observed_at) && (
                  <p className="muted small">{freshnessText(summary.stock_decision_observed_at)}</p>
                )}
              </>
            )}
          </section>
        </>
      )}
    </main>
  );
}
