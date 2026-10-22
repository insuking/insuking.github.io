import { useEffect, useState } from "react";
import {
  activateEmergencyStop,
  fetchBalance,
  fetchBalanceHistory,
  fetchDashboardSummary,
  fetchKakaoLoginUrl,
  fetchPendingApprovals,
} from "../api/client";
import { RecommendationCard } from "../components/RecommendationCard";
import type { DashboardSummary } from "../types/dashboard";
import type { Balance, BalanceHistory } from "../types/account";
import type { PendingApproval } from "../types/approval";
import { currentUserId } from "../auth";
import { usePolledFetch } from "../hooks/usePolledFetch";
import "./HomePage.css";

const HEALTH_LABEL: Record<string, string> = {
  HEALTHY: "정상",
  DEGRADED: "저하",
  RECOVERING: "복구중",
  PAUSED: "일시중지",
  CRITICAL: "위험",
  OFFLINE: "오프라인",
};

const ASSET_LABEL: Record<string, string> = {
  STOCK: "주식",
  CRYPTO: "코인",
};

const STATE_LABEL: Record<string, string> = {
  OPEN: "진입",
  T1_FILLED: "T1 체결",
  T2_FILLED: "T2 체결",
  RUNNER: "러너",
  CLOSED: "종료",
};

const SUMMARY_POLL_MS = 30_000;
const BALANCE_POLL_MS = 30_000;
const HISTORY_WINDOWS = ["1d", "1w", "1m", "all"] as const;

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

function buildSparklinePoints(values: number[], width: number, height: number): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/**
 * Radar tab / home screen (P21, extended in P42/P45) - docs/MASTER_SPEC.md
 * UX PRINCIPLES: within five seconds the reader must be able to answer
 * "is the market safe right now? is there a recommendation? does
 * something need approval? are open positions safe? how much of today's
 * risk budget is left?" P45 adds the real combined total-assets figure
 * and its trend chart (`/api/dashboard/balance`, its own poll - separate
 * from `/summary` since it hits real KIS/Upbit account APIs per request,
 * same reasoning as `/positions/live-prices`), and a 긴급정지 button
 * wired to the real manual kill-switch endpoint.
 */
export function HomePage() {
  const userId = currentUserId();
  const {
    data: summary,
    error: loadError,
    refetch,
  } = usePolledFetch<DashboardSummary>(fetchDashboardSummary, SUMMARY_POLL_MS);
  const { data: balance } = usePolledFetch<Balance>(fetchBalance, BALANCE_POLL_MS);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [pendingError, setPendingError] = useState(false);
  const [historyWindow, setHistoryWindow] = useState<(typeof HISTORY_WINDOWS)[number]>("1d");
  const [history, setHistory] = useState<BalanceHistory | null>(null);
  const [emergencyBusy, setEmergencyBusy] = useState(false);
  const [emergencyMessage, setEmergencyMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchBalanceHistory("1d")
      .then((result) => {
        if (!cancelled) setHistory(result);
      })
      .catch(() => {
        if (!cancelled) setHistory(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleKakaoLogin() {
    setLoginError(null);
    try {
      const { authorize_url } = await fetchKakaoLoginUrl();
      window.location.href = authorize_url;
    } catch {
      setLoginError("카카오 로그인을 시작할 수 없습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleCheckApprovals() {
    if (!userId) return;
    setPendingLoading(true);
    setPendingError(false);
    try {
      const result = await fetchPendingApprovals(userId);
      setPending(result.approvals);
    } catch {
      setPendingError(true);
    } finally {
      setPendingLoading(false);
    }
  }

  async function handleHistoryWindowChange(window: (typeof HISTORY_WINDOWS)[number]) {
    setHistoryWindow(window);
    try {
      const result = await fetchBalanceHistory(window);
      setHistory(result);
    } catch {
      setHistory(null);
    }
  }

  async function handleEmergencyStop() {
    if (!userId) {
      setEmergencyMessage("카카오 로그인 후 긴급정지를 사용할 수 있습니다.");
      return;
    }
    setEmergencyBusy(true);
    setEmergencyMessage(null);
    try {
      await activateEmergencyStop(userId);
      setEmergencyMessage("긴급정지가 활성화되었습니다. 새로운 거래가 차단됩니다.");
      refetch();
    } catch {
      setEmergencyMessage("긴급정지 요청에 실패했습니다. 다시 시도해주세요.");
    } finally {
      setEmergencyBusy(false);
    }
  }

  const healthState = summary?.overall_health ?? null;
  const healthy = healthState === "HEALTHY";
  const killSwitchActive = summary?.risk_used?.kill_switch_active ?? false;
  const remainingLossLimit =
    summary?.risk_used != null ? Math.max(0, summary.risk_used.daily_loss_limit - summary.risk_used.daily_loss) : null;

  const sparkline = history && history.snapshots.length >= 2
    ? buildSparklinePoints(history.snapshots.map((s) => s.total_assets), 280, 60)
    : null;

  return (
    <main className="page">
      <header className="app-header">
        <h1>Multi Asset Radar</h1>
        <div className="home-header-actions">
          <span className={`status-badge status-${healthy ? "ok" : "warn"}`}>
            시스템 ● {healthState ? HEALTH_LABEL[healthState] ?? healthState : "확인 중"}
          </span>
          <button
            type="button"
            className={`emergency-stop-button${killSwitchActive ? " emergency-stop-button--active" : ""}`}
            onClick={handleEmergencyStop}
            disabled={emergencyBusy}
          >
            {killSwitchActive ? "긴급정지 작동중" : "긴급정지"}
          </button>
        </div>
      </header>
      {emergencyMessage && <p className="muted small">{emergencyMessage}</p>}
      <a href="#/emergency" className="muted small">
        비상정지 감사 로그 보기 →
      </a>

      {!userId && (
        <section className="card">
          <p className="card-title">카카오 로그인이 필요합니다</p>
          <p className="muted">승인 알림을 받고 승인 화면을 이용하려면 로그인하세요.</p>
          <button type="button" className="cta" onClick={handleKakaoLogin}>
            카카오 로그인
          </button>
          {loginError && <p className="muted">{loginError}</p>}
        </section>
      )}

      <div className="stat-grid">
        <div className="stat-card">
          <span className="stat-card__label">총자산</span>
          <span className="stat-card__value">
            {balance ? `${numberFormatter.format(balance.total_assets)}` : "—"}
          </span>
        </div>
        <div className="stat-card">
          <span className="stat-card__label">오늘 손실</span>
          <span className="stat-card__value stat-card__value--loss">
            {summary?.risk_used ? numberFormatter.format(summary.risk_used.daily_loss) : "—"}
          </span>
        </div>
        <div className="stat-card">
          <span className="stat-card__label">남은 손실한도</span>
          <span className="stat-card__value">{remainingLossLimit != null ? numberFormatter.format(remainingLossLimit) : "—"}</span>
        </div>
        <div className="stat-card">
          <span className="stat-card__label">승인 대기</span>
          <span className="stat-card__value">{summary?.pending_approvals ?? "—"}</span>
        </div>
        <div className="stat-card">
          <span className="stat-card__label">보유 포지션</span>
          <span className="stat-card__value">{summary?.positions.length ?? "—"}</span>
        </div>
      </div>

      <section className="card">
        <div className="card-row" style={{ padding: 0, marginBottom: 10 }}>
          <p className="card-title" style={{ margin: 0 }}>
            자산 추이
          </p>
          <div className="history-window-tabs">
            {HISTORY_WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                className={`history-window-tab${historyWindow === w ? " history-window-tab--active" : ""}`}
                onClick={() => handleHistoryWindowChange(w)}
              >
                {w.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        {sparkline ? (
          <svg viewBox="0 0 280 60" className="sparkline" preserveAspectRatio="none">
            <polyline points={sparkline} fill="none" stroke="var(--color-gain)" strokeWidth="2" />
          </svg>
        ) : (
          <p className="muted small">
            아직 자산 추이 데이터가 충분하지 않습니다. 스케줄러가 실행되면 자동으로 쌓입니다.
          </p>
        )}
      </section>

      <section className="card">
        <p className="card-title">승인 대기 {summary?.pending_approvals ?? 0}건</p>
        <button
          type="button"
          className="cta"
          disabled={!summary || summary.pending_approvals === 0 || !userId || pendingLoading}
          onClick={handleCheckApprovals}
        >
          {pendingLoading ? "확인 중..." : "지금 확인"}
        </button>
        {!userId && summary && summary.pending_approvals > 0 && (
          <p className="muted small">카카오 로그인 후 확인할 수 있습니다.</p>
        )}
        {pendingError && (
          <p className="muted small">승인 목록을 불러오지 못했습니다. 카카오톡 메시지를 확인해주세요.</p>
        )}
        {pending && pending.length === 0 && <p className="muted small">대기 중인 승인이 없습니다.</p>}
        {pending && pending.length > 0 && (
          <>
            {pending.map((approval) => (
              <div className="card-row" key={approval.id}>
                <span>
                  {approval.symbol} · {ASSET_LABEL[approval.asset_type] ?? approval.asset_type} (점수{" "}
                  {Math.round(approval.score)})
                </span>
                <span className="muted">{Math.max(0, Math.floor(approval.remaining_seconds / 60))}분 남음</span>
              </div>
            ))}
            <p className="muted small">카카오톡으로 받은 메시지에서 실제 승인/거절을 진행하세요.</p>
          </>
        )}
      </section>

      {summary && summary.positions.length > 0 && (
        <section className="card">
          <p className="card-title">보유 포지션 {summary.positions.length}건</p>
          {summary.positions.map((position) => (
            <div className="card-row" key={position.id}>
              <span>{position.symbol}</span>
              <span className="muted">{STATE_LABEL[position.state] ?? position.state}</span>
            </div>
          ))}
          <p className="muted small">실시간 손익은 포지션 탭에서 확인할 수 있습니다.</p>
        </section>
      )}

      <section>
        <p className="card-title">TOP 추천</p>
        {summary && summary.top_opportunities.length === 0 && (
          <p className="muted">현재 추천이 없습니다.</p>
        )}
        {summary?.top_opportunities.map((rec) => (
          <RecommendationCard key={rec.id} recommendation={rec} />
        ))}
      </section>

      {loadError && (
        <section className="card">
          <p className="muted">데이터를 불러오지 못했습니다.</p>
          <button type="button" className="retry-button" onClick={refetch}>
            다시 시도
          </button>
        </section>
      )}
    </main>
  );
}
