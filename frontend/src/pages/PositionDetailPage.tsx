import { useState } from "react";
import {
  ApprovalApiError,
  closePosition,
  fetchPositionDetail,
  setPositionGuardianActive,
} from "../api/client";
import { HoldToConfirmButton } from "../components/HoldToConfirmButton";
import { currentUserId } from "../auth";
import { usePolledFetch } from "../hooks/usePolledFetch";
import type { PositionDetail } from "../types/position";
import "./PositionDetailPage.css";

const DETAIL_POLL_MS = 15_000;

const STATE_LABEL: Record<string, string> = {
  OPEN: "진입",
  T1_FILLED: "T1 체결",
  T2_FILLED: "T2 체결",
  RUNNER: "러너",
  CLOSED: "종료",
};

// Real state order this project's accounting engine actually produces
// (app/partial_profit/accounting.py) - T2_FILLED is included for
// completeness (the domain enum has it, and older/manually-seeded rows
// may carry it) even though that engine jumps straight from T1_FILLED to
// RUNNER on a real T2 fill.
const PROGRESS_STEPS = ["OPEN", "T1_FILLED", "T2_FILLED", "RUNNER", "CLOSED"] as const;

const PROTECTIVE_ORDER_LABEL: Record<string, string> = {
  STOP: "손절가",
  T1: "T1 목표가",
  T2: "T2 목표가",
  TRAILING: "트레일링 스탑",
};

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });
const pnlFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

function pnlClass(value: number): string {
  if (value > 0) return "pnl-gain";
  if (value < 0) return "pnl-loss";
  return "pnl-flat";
}

function formatPnl(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${pnlFormatter.format(value)}`;
}

interface PositionDetailPageProps {
  positionId: string;
}

/**
 * 포지션 상세 (P46) - the SmartCoin mockups' "포지션 관리"(07) +
 * "분할청산 진행"(08) screens combined into one detail page. Progress is
 * shown via `Position.state` - already real, fill-derived by
 * `PartialProfitService` - never a computed fill percentage: `Position`
 * has no `trade_plan_id` link back to the `TradePlan` that would carry
 * `t1_percent`/`t2_percent`, so a percentage-based progress bar would
 * fabricate a precision this schema doesn't have (see
 * `app/api/positions.py`'s own module docstring). Guardian pause and
 * "즉시 청산" both require a hold-to-confirm gesture before calling their
 * real endpoints - the same "explicit human action every time" rule this
 * whole project applies to every real-money action.
 */
export function PositionDetailPage({ positionId }: PositionDetailPageProps) {
  const userId = currentUserId();
  const {
    data: position,
    error: loadError,
    refetch,
  } = usePolledFetch<PositionDetail>(() => fetchPositionDetail(positionId), DETAIL_POLL_MS);

  const [guardianBusy, setGuardianBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [closeResult, setCloseResult] = useState<PositionDetail["state"] | null>(null);

  async function handleGuardianToggle(position: PositionDetail) {
    if (!userId) {
      setMessage("카카오 로그인 후 이용할 수 있습니다.");
      return;
    }
    setGuardianBusy(true);
    setMessage(null);
    try {
      await setPositionGuardianActive(position.id, userId, !position.guardian_active);
      refetch();
    } catch (err) {
      setMessage(err instanceof ApprovalApiError ? err.detail : "요청을 처리하지 못했습니다.");
    } finally {
      setGuardianBusy(false);
    }
  }

  async function handleClose(position: PositionDetail) {
    if (!userId) {
      setMessage("카카오 로그인 후 이용할 수 있습니다.");
      return;
    }
    setMessage(null);
    try {
      const result = await closePosition(position.id, userId);
      setCloseResult(result.state);
      setMessage("청산 주문이 접수되었습니다.");
      refetch();
    } catch (err) {
      setMessage(err instanceof ApprovalApiError ? err.detail : "청산 요청에 실패했습니다.");
    }
  }

  return (
    <main className="page">
      <header className="app-header">
        <a href="#/positions" className="back-link">
          ← 포지션
        </a>
        <h1>{position?.symbol ?? "포지션 상세"}</h1>
      </header>

      {loadError && !position && (
        <section className="card">
          <p className="muted">데이터를 불러오지 못했습니다.</p>
          <button type="button" className="retry-button" onClick={refetch}>
            다시 시도
          </button>
        </section>
      )}

      {!position && !loadError && <p className="muted">불러오는 중...</p>}

      {position && (
        <>
          <section className="card">
            <div className="position-detail__progress">
              {PROGRESS_STEPS.map((step, index) => {
                const currentIndex = PROGRESS_STEPS.indexOf(position.state as (typeof PROGRESS_STEPS)[number]);
                const reached = currentIndex >= 0 && index <= currentIndex;
                return (
                  <div key={step} className={`position-detail__step${reached ? " position-detail__step--reached" : ""}`}>
                    <span className="position-detail__step-dot" />
                    <span className="position-detail__step-label">{STATE_LABEL[step]}</span>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="card">
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
              <span>{position.current_price != null ? numberFormatter.format(position.current_price) : "—"}</span>
            </div>
            <div className="card-row">
              <span>평가손익</span>
              {position.unrealized_pnl != null && position.unrealized_pnl_pct != null ? (
                <span className={pnlClass(position.unrealized_pnl)}>
                  {formatPnl(position.unrealized_pnl)} ({position.unrealized_pnl_pct >= 0 ? "+" : ""}
                  {position.unrealized_pnl_pct.toFixed(2)}%)
                </span>
              ) : (
                <span className="muted">—</span>
              )}
            </div>
          </section>

          <section className="card">
            <p className="card-title">보호 주문</p>
            {position.protective_orders.length === 0 && <p className="muted small">설정된 보호 주문이 없습니다.</p>}
            {position.protective_orders.map((order, i) => (
              <div className="card-row" key={`${order.kind}-${i}`}>
                <span>
                  {PROTECTIVE_ORDER_LABEL[order.kind] ?? order.kind}
                  {!order.active && " (비활성)"}
                </span>
                <span>{numberFormatter.format(order.trigger_price)}</span>
              </div>
            ))}
          </section>

          <section className="card">
            <div className="card-row">
              <span>자동관리 (Guardian)</span>
              <span className="muted">{position.guardian_active ? "활성" : "일시정지"}</span>
            </div>
            <button
              type="button"
              className="secondary-button"
              disabled={guardianBusy || position.state === "CLOSED"}
              onClick={() => handleGuardianToggle(position)}
            >
              {position.guardian_active ? "자동관리 일시정지" : "자동관리 재개"}
            </button>
          </section>

          {message && <p className="muted small">{message}</p>}

          {position.state !== "CLOSED" && closeResult !== "CLOSED" && (
            <section className="card">
              <p className="card-title">즉시 청산</p>
              <p className="muted small">현재 수량 전체를 시장가로 즉시 매도합니다. 되돌릴 수 없습니다.</p>
              <HoldToConfirmButton
                label="눌러서 즉시 청산"
                holdingLabel="계속 누르면 청산됩니다..."
                busyLabel="청산 처리 중..."
                variant="danger"
                onConfirm={() => handleClose(position)}
              />
            </section>
          )}
        </>
      )}
    </main>
  );
}
