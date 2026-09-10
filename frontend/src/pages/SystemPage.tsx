import { useEffect, useState } from "react";
import { fetchDashboardSummary, fetchIncidents } from "../api/client";
import type { DashboardSummary, IncidentOut } from "../types/dashboard";

const HEALTH_LABEL: Record<string, string> = {
  HEALTHY: "정상",
  DEGRADED: "저하",
  RECOVERING: "복구중",
  PAUSED: "일시중지",
  CRITICAL: "위험",
  OFFLINE: "오프라인",
};

/** How long ago a scan last wrote data, so an investor can tell "지금 이
 * 화면이 실제로 최신 스캔 결과인지" at a glance, not just that the service
 * process is up. */
function freshnessText(updatedAt: string | null): string {
  if (updatedAt === null) return "데이터 없음";
  const updated = new Date(updatedAt);
  if (Number.isNaN(updated.getTime())) return "데이터 없음";
  const minutesAgo = Math.max(0, Math.round((Date.now() - updated.getTime()) / 60000));
  if (minutesAgo < 1) return "방금 갱신됨";
  if (minutesAgo < 60) return `${minutesAgo}분 전`;
  const hoursAgo = Math.round(minutesAgo / 60);
  return `${hoursAgo}시간 전`;
}

/** 시스템 tab - P19's self-healing/watchdog state made visible: per-service
 * health (never just a single overall dot) and the recent incident log,
 * including whether each one required a human to step in. */
export function SystemPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [incidents, setIncidents] = useState<IncidentOut[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchDashboardSummary(), fetchIncidents()])
      .then(([summaryData, incidentData]) => {
        if (!cancelled) {
          setSummary(summaryData);
          setIncidents(incidentData);
        }
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
        <h1>시스템</h1>
      </header>

      {loadError && <p className="muted">데이터를 불러오지 못했습니다.</p>}

      {summary && (
        <>
          <section className="card">
            <p className="card-title">서비스 상태</p>
            {summary.service_health.map((sh) => (
              <div className="card-row" key={sh.service}>
                <span>{sh.service}</span>
                <span className="muted">{HEALTH_LABEL[sh.state] ?? sh.state}</span>
              </div>
            ))}
          </section>
          <section className="card">
            <p className="card-title">스캔 데이터 최신성</p>
            <div className="card-row">
              <span>국내 시장 (KOSPI/KOSDAQ)</span>
              <span className="muted">{freshnessText(summary.market_regime_updated_at)}</span>
            </div>
            <div className="card-row">
              <span>BTC (Upbit KRW-BTC)</span>
              <span className="muted">{freshnessText(summary.btc_regime_updated_at)}</span>
            </div>
            <div className="card-row">
              <span>오늘의 판정</span>
              <span className="muted">{freshnessText(summary.stock_decision_observed_at)}</span>
            </div>
            <p className="muted small">
              스캐너가 실제로 최근에 데이터를 갱신했는지 확인하는 지표입니다. 오래 전 시각이 표시되면 스케줄러가
              멈췄을 수 있습니다.
            </p>
          </section>
        </>
      )}

      <section className="card">
        <p className="card-title">최근 인시던트 ({summary?.open_incidents ?? 0}건 미해결)</p>
        {incidents !== null && incidents.length === 0 && <p className="muted">인시던트가 없습니다.</p>}
        {incidents?.map((incident) => (
          <div className="card-row" key={incident.id}>
            <span>
              {incident.service} · {incident.failure_type}
            </span>
            <span className="muted">
              {incident.recovered_at
                ? "복구됨"
                : incident.human_action_required
                  ? "확인 필요"
                  : "자동복구 시도중"}
            </span>
          </div>
        ))}
      </section>
    </main>
  );
}
