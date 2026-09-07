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
        <section className="card">
          <p className="card-title">서비스 상태</p>
          {summary.service_health.map((sh) => (
            <div className="card-row" key={sh.service}>
              <span>{sh.service}</span>
              <span className="muted">{HEALTH_LABEL[sh.state] ?? sh.state}</span>
            </div>
          ))}
        </section>
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
