import { fetchDashboardSummary } from "../api/client";
import { RecommendationCard } from "../components/RecommendationCard";
import type { DashboardSummary } from "../types/dashboard";
import { usePolledFetch } from "../hooks/usePolledFetch";

const RECOMMENDATIONS_POLL_MS = 30_000;

/** 추천 tab (P21, extended in P42) - the full opportunity list
 * `/api/dashboard/summary` already carries (`top_opportunities`), given
 * its own screen rather than confined to the home screen's glance-sized
 * slice. Auto-refreshes every 30s with a retry button on failure. */
export function RecommendationsPage() {
  const {
    data: summary,
    error: loadError,
    refetch,
  } = usePolledFetch<DashboardSummary>(fetchDashboardSummary, RECOMMENDATIONS_POLL_MS);
  const recommendations = summary?.top_opportunities ?? null;

  return (
    <main className="page">
      <header className="app-header">
        <h1>추천</h1>
      </header>

      {recommendations === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && (
        <section className="card">
          <p className="muted">데이터를 불러오지 못했습니다.</p>
          <button type="button" className="retry-button" onClick={refetch}>
            다시 시도
          </button>
        </section>
      )}
      {recommendations?.length === 0 && (
        <section className="card">
          <p className="muted">현재 유효한 추천이 없습니다.</p>
        </section>
      )}
      {recommendations?.map((rec) => (
        <RecommendationCard key={rec.id} recommendation={rec} />
      ))}
    </main>
  );
}
