import { useMemo } from "react";
import { fetchDashboardSummary, fetchPositionsLivePrices } from "../api/client";
import type { Position } from "../types/domain";
import type { PositionPriceOut } from "../types/dashboard";
import { usePolledFetch } from "../hooks/usePolledFetch";

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });
const pnlFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

const STATE_LABEL: Record<string, string> = {
  OPEN: "진입",
  T1_FILLED: "T1 체결",
  T2_FILLED: "T2 체결",
  RUNNER: "러너",
  CLOSED: "종료",
};

const POSITIONS_POLL_MS = 30_000;
// Live quotes hit real KIS/Upbit APIs per position - polled on its own,
// slower cadence than the position list itself (P42 item 3's own docstring
// on backend/app/api/dashboard.py's `/positions/live-prices`).
const LIVE_PRICES_POLL_MS = 20_000;

function pnlClass(value: number): string {
  if (value > 0) return "pnl-gain";
  if (value < 0) return "pnl-loss";
  return "pnl-flat";
}

function formatPnl(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${pnlFormatter.format(value)}`;
}

/** 포지션 tab (P21, extended in P42) - "are open positions safe?"
 * (docs/MASTER_SPEC.md UX PRINCIPLES): each position states its Guardian
 * protection status in words, not just a color dot, per P21's "never
 * color-only signaling". P42 adds a real live price/unrealized P&L per
 * position, fetched separately from the position list itself since it
 * makes real external API calls. */
export function PositionsPage() {
  const {
    data: summary,
    error: loadError,
    refetch,
  } = usePolledFetch(fetchDashboardSummary, POSITIONS_POLL_MS);
  const { data: livePrices } = usePolledFetch(fetchPositionsLivePrices, LIVE_PRICES_POLL_MS);

  const positions: Position[] | null = summary?.positions ?? null;

  const priceBySymbol = useMemo(() => {
    const map = new Map<string, PositionPriceOut>();
    for (const price of livePrices?.prices ?? []) {
      map.set(price.symbol, price);
    }
    return map;
  }, [livePrices]);

  return (
    <main className="page">
      <header className="app-header">
        <h1>포지션</h1>
      </header>

      {positions === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && (
        <section className="card">
          <p className="muted">데이터를 불러오지 못했습니다.</p>
          <button type="button" className="retry-button" onClick={refetch}>
            다시 시도
          </button>
        </section>
      )}
      {positions?.length === 0 && (
        <section className="card">
          <p className="muted">보유 중인 포지션이 없습니다.</p>
        </section>
      )}
      {positions?.map((position) => {
        const livePrice = priceBySymbol.get(position.symbol);
        return (
          <section className="card" key={position.id}>
            <div className="card-row">
              <span className="card-title">{position.symbol}</span>
              <span className="muted">{STATE_LABEL[position.state] ?? position.state}</span>
            </div>
            <div className="card-row">
              <span>수량</span>
              <span>{numberFormatter.format(position.quantity)}</span>
            </div>
            <div className="card-row">
              <span>평균단가</span>
              <span>{numberFormatter.format(position.avg_entry_price)}</span>
            </div>
            <div className="card-row">
              <span>현재가</span>
              <span>
                {livePrice?.current_price != null ? numberFormatter.format(livePrice.current_price) : "—"}
              </span>
            </div>
            <div className="card-row">
              <span>평가손익</span>
              {livePrice?.unrealized_pnl != null && livePrice.unrealized_pnl_pct != null ? (
                <span className={pnlClass(livePrice.unrealized_pnl)}>
                  {formatPnl(livePrice.unrealized_pnl)} ({livePrice.unrealized_pnl_pct >= 0 ? "+" : ""}
                  {livePrice.unrealized_pnl_pct.toFixed(2)}%)
                </span>
              ) : (
                <span className="muted">—</span>
              )}
            </div>
            <div className="card-row">
              <span>손절가</span>
              <span>{numberFormatter.format(position.stop_price)}</span>
            </div>
            <div className="card-row">
              <span>Guardian 보호</span>
              <span className="muted">{position.guardian_active ? "활성" : "비활성"}</span>
            </div>
          </section>
        );
      })}
    </main>
  );
}
