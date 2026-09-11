import { useState } from "react";
import { fetchDashboardSummary, fetchKakaoLoginUrl, fetchPendingApprovals } from "../api/client";
import { RecommendationCard } from "../components/RecommendationCard";
import type { DashboardSummary } from "../types/dashboard";
import type { PendingApproval } from "../types/approval";
import { currentUserId } from "../auth";
import { usePolledFetch } from "../hooks/usePolledFetch";

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

const SUMMARY_POLL_MS = 30_000;

/**
 * Radar tab / home screen (P21, extended in P42) - docs/MASTER_SPEC.md UX
 * PRINCIPLES: within five seconds the reader must be able to answer "is
 * the market safe right now? is there a recommendation? does something
 * need approval? are open positions safe? how much of today's risk budget
 * is left?" - one fetch (`/api/dashboard/summary`) backs every widget
 * below so there's no waterfall of requests delaying that answer. That
 * fetch now also auto-refreshes every 30s and exposes a retry button on
 * failure (P42 items 2/5). "지금 확인" (P42 item 1) reveals the real
 * pending-approval list inline via the read-only `/api/approvals` list -
 * it never lets you decide from here, since only the Kakao-delivered
 * token can still do that (see backend/app/api/approvals.py's docstring).
 */
export function HomePage() {
  const userId = currentUserId();
  const {
    data: summary,
    error: loadError,
    refetch,
  } = usePolledFetch<DashboardSummary>(fetchDashboardSummary, SUMMARY_POLL_MS);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [pendingError, setPendingError] = useState(false);

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

  const healthState = summary?.overall_health ?? null;
  const healthy = healthState === "HEALTHY";

  return (
    <main className="page">
      <header className="app-header">
        <h1>Multi Asset Radar</h1>
        <span className={`status-badge status-${healthy ? "ok" : "warn"}`}>
          SYSTEM ● {healthState ? HEALTH_LABEL[healthState] ?? healthState : "확인 중"}
        </span>
      </header>

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

      <section className="card">
        <div className="card-row">
          <span>국내시장</span>
          <span className="muted">{summary?.market_regime ?? "데이터 대기"}</span>
        </div>
        <div className="card-row">
          <span>BTC</span>
          <span className="muted">{summary?.btc_regime ?? "데이터 대기"}</span>
        </div>
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

      <section className="card">
        <p className="card-title">보유종목 {summary?.positions.length ?? 0}</p>
        {summary?.risk_used ? (
          <>
            <p className="muted">
              오늘 손실 {Math.round(summary.risk_used.daily_loss).toLocaleString("ko-KR")} /{" "}
              {Math.round(summary.risk_used.daily_loss_limit).toLocaleString("ko-KR")}
            </p>
            <p className="muted">
              위험사용{" "}
              {((summary.risk_used.exposure / summary.risk_used.exposure_limit) * 100).toFixed(1)}%
              {summary.risk_used.kill_switch_active && " · 킬스위치 작동중"}
            </p>
          </>
        ) : (
          <p className="muted">위험 데이터 대기</p>
        )}
      </section>

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
