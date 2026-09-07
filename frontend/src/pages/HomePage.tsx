import { useEffect, useState } from "react";
import { fetchDashboardSummary, fetchKakaoLoginUrl } from "../api/client";
import { RecommendationCard } from "../components/RecommendationCard";
import type { DashboardSummary } from "../types/dashboard";
import { currentUserId } from "../auth";

const HEALTH_LABEL: Record<string, string> = {
  HEALTHY: "정상",
  DEGRADED: "저하",
  RECOVERING: "복구중",
  PAUSED: "일시중지",
  CRITICAL: "위험",
  OFFLINE: "오프라인",
};

/**
 * Radar tab / home screen (P21) - docs/MASTER_SPEC.md UX PRINCIPLES: within
 * five seconds the reader must be able to answer "is the market safe right
 * now? is there a recommendation? does something need approval? are open
 * positions safe? how much of today's risk budget is left?" - one fetch
 * (`/api/dashboard/summary`) backs every widget below so there's no
 * waterfall of requests delaying that answer.
 */
export function HomePage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const userId = currentUserId();

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

  async function handleKakaoLogin() {
    setLoginError(null);
    try {
      const { authorize_url } = await fetchKakaoLoginUrl();
      window.location.href = authorize_url;
    } catch {
      setLoginError("카카오 로그인을 시작할 수 없습니다. 잠시 후 다시 시도해주세요.");
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
        <button type="button" className="cta" disabled={!summary || summary.pending_approvals === 0}>
          지금 확인
        </button>
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

      {loadError && <p className="muted">데이터를 불러오지 못했습니다.</p>}
    </main>
  );
}
