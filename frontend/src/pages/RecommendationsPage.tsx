import { useEffect, useState } from "react";
import { fetchDashboardSummary } from "../api/client";
import { RecommendationCard } from "../components/RecommendationCard";
import type { Recommendation } from "../types/domain";

/** 추천 tab - the full opportunity list `/api/dashboard/summary` already
 * carries (`top_opportunities`), given its own screen rather than confined
 * to the home screen's glance-sized slice. */
export function RecommendationsPage() {
  const [recommendations, setRecommendations] = useState<Recommendation[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchDashboardSummary()
      .then((data) => {
        if (!cancelled) setRecommendations(data.top_opportunities);
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
        <h1>추천</h1>
      </header>

      {recommendations === null && !loadError && <p className="muted">불러오는 중...</p>}
      {loadError && <p className="muted">데이터를 불러오지 못했습니다.</p>}
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
