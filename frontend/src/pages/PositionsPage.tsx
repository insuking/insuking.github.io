import { useEffect, useState } from "react";
import { fetchDashboardSummary } from "../api/client";
import type { Position } from "../types/domain";

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });

const STATE_LABEL: Record<string, string> = {
  OPEN: "진입",
  T1_FILLED: "T1 체결",
  T2_FILLED: "T2 체결",
  RUNNER: "러너",
  CLOSED: "종료",
};

/** 포지션 tab - "are open positions safe?" (docs/MASTER_SPEC.md UX
 * PRINCIPLES): each position states its Guardian protection status in
 * words, not just a color dot, per P21's "never color-only signaling". */
export function PositionsPage() {
  const [positions, setPositions] = useState<Position[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchDashboardSummary()
      .then((data) => {
        if (!cancelled) setPositions(data.positions);
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
        <h1>포지션</h1>
      </header>

      {positions === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && <p className="muted">데이터를 불러오지 못했습니다.</p>}
      {positions?.length === 0 && (
        <section className="card">
          <p className="muted">보유 중인 포지션이 없습니다.</p>
        </section>
      )}
      {positions?.map((position) => (
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
            <span>손절가</span>
            <span>{numberFormatter.format(position.stop_price)}</span>
          </div>
          <div className="card-row">
            <span>Guardian 보호</span>
            <span className="muted">{position.guardian_active ? "활성" : "비활성"}</span>
          </div>
        </section>
      ))}
    </main>
  );
}
