import { useState } from "react";
import {
  ApprovalApiError,
  activateEmergencyStop,
  clearEmergencyStop,
  fetchDashboardSummary,
  fetchRiskStateHistory,
} from "../api/client";
import { HoldToConfirmButton } from "../components/HoldToConfirmButton";
import { currentUserId } from "../auth";
import { usePolledFetch } from "../hooks/usePolledFetch";
import type { DashboardSummary } from "../types/dashboard";
import type { RiskStateHistory } from "../types/position";
import "./EmergencyStopPage.css";

const STATUS_POLL_MS = 15_000;
const HISTORY_POLL_MS = 15_000;

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("ko-KR", { hour12: false });
  } catch {
    return iso;
  }
}

/**
 * 비상정지와 복구 (P46) - the SmartCoin mockups' "비상정지와 복구" screen:
 * real current kill-switch status plus a real audit log, not a fabricated
 * activity feed. `risk_states` (P18) is already append-only - see
 * `RiskStateRow`'s own docstring - so `GET /api/dashboard/risk-states/
 * history` just reads back every automatic P18 evaluation and every
 * manual activate/clear that has ever actually happened. Both actions
 * here require a hold-to-confirm gesture before calling the same real
 * endpoints `HomePage`'s quick-action button already uses.
 */
export function EmergencyStopPage() {
  const userId = currentUserId();
  const {
    data: summary,
    error: statusError,
    refetch: refetchStatus,
  } = usePolledFetch<DashboardSummary>(fetchDashboardSummary, STATUS_POLL_MS);
  const { data: history, error: historyError, refetch: refetchHistory } = usePolledFetch<RiskStateHistory>(
    fetchRiskStateHistory,
    HISTORY_POLL_MS,
  );

  const [message, setMessage] = useState<string | null>(null);

  const killSwitchActive = summary?.risk_used?.kill_switch_active ?? false;

  async function handleActivate() {
    if (!userId) {
      setMessage("카카오 로그인 후 긴급정지를 사용할 수 있습니다.");
      return;
    }
    setMessage(null);
    try {
      await activateEmergencyStop(userId);
      setMessage("긴급정지가 활성화되었습니다.");
      refetchStatus();
      refetchHistory();
    } catch (err) {
      setMessage(err instanceof ApprovalApiError ? err.detail : "긴급정지 요청에 실패했습니다.");
    }
  }

  async function handleClear() {
    if (!userId) {
      setMessage("카카오 로그인 후 이용할 수 있습니다.");
      return;
    }
    setMessage(null);
    try {
      await clearEmergencyStop(userId);
      setMessage("긴급정지가 해제되었습니다.");
      refetchStatus();
      refetchHistory();
    } catch (err) {
      setMessage(err instanceof ApprovalApiError ? err.detail : "요청에 실패했습니다.");
    }
  }

  return (
    <main className="page">
      <header className="app-header">
        <a href="#/radar" className="back-link">
          ← 홈
        </a>
        <h1>비상정지와 복구</h1>
      </header>

      <section className="card">
        <div className="card-row">
          <span>현재 상태</span>
          <span className={`status-badge status-${killSwitchActive ? "warn" : "ok"}`}>
            {killSwitchActive ? "긴급정지 작동중" : "정상"}
          </span>
        </div>
        {summary?.risk_used?.kill_switch_reason && (
          <p className="muted small">{summary.risk_used.kill_switch_reason}</p>
        )}
        {statusError && <p className="muted small">상태를 불러오지 못했습니다.</p>}
      </section>

      {message && <p className="muted small">{message}</p>}

      <section className="card">
        {killSwitchActive ? (
          <HoldToConfirmButton
            label="눌러서 복구 (거래 재개)"
            holdingLabel="계속 누르면 복구됩니다..."
            busyLabel="복구 처리 중..."
            onConfirm={handleClear}
          />
        ) : (
          <HoldToConfirmButton
            label="눌러서 긴급정지"
            holdingLabel="계속 누르면 긴급정지됩니다..."
            busyLabel="긴급정지 처리 중..."
            variant="danger"
            onConfirm={handleActivate}
          />
        )}
      </section>

      <section className="card">
        <p className="card-title">감사 로그</p>
        {historyError && <p className="muted small">로그를 불러오지 못했습니다.</p>}
        {history && history.snapshots.length === 0 && <p className="muted small">기록이 없습니다.</p>}
        {history?.snapshots.map((snapshot, i) => (
          <div className="emergency-log-row" key={`${snapshot.as_of}-${i}`}>
            <div className="card-row">
              <span className={snapshot.kill_switch_active ? "pnl-loss" : "pnl-gain"}>
                {snapshot.kill_switch_active ? "긴급정지 활성화" : "정상"}
              </span>
              <span className="muted small">{formatTime(snapshot.as_of)}</span>
            </div>
            {snapshot.kill_switch_reason && <p className="muted small">{snapshot.kill_switch_reason}</p>}
            <p className="muted small">
              손실 {numberFormatter.format(snapshot.daily_loss)} / {numberFormatter.format(snapshot.daily_loss_limit)}
              {"  ·  "}
              노출 {numberFormatter.format(snapshot.exposure)} / {numberFormatter.format(snapshot.exposure_limit)}
            </p>
          </div>
        ))}
      </section>
    </main>
  );
}
