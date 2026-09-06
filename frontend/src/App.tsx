import { useEffect, useState } from "react";
import { fetchReadiness } from "./api/client";
import { ApprovalPage } from "./components/ApprovalPage";
import { RecommendationCard } from "./components/RecommendationCard";
import type { Recommendation } from "./types/domain";
import "./App.css";

// No router dependency yet - a single mobile deep-link path
// (/approve/:token, from the Kakao "send to me" message, see
// app/approval/service.py's notify()) is the only route besides the home
// screen, so a plain pathname match covers it without pulling in
// react-router for one case.
function matchApprovalRoute(pathname: string): string | null {
  const match = /^\/approve\/([^/]+)$/.exec(pathname);
  return match ? match[1] : null;
}

// The frontend has no Kakao login UI yet (P12 built the backend OAuth flow
// only) - once a real login redirect lands, it should store the
// authenticated user's id here. Until then this is the honestly-documented
// gap: ApprovalPage shows "카카오 로그인이 필요합니다" when it's absent.
function currentUserId(): string | null {
  try {
    return localStorage.getItem("userId");
  } catch {
    return null;
  }
}

type SystemStatus = "checking" | "정상" | "점검필요";

// Preview data only - no live recommendation feed exists yet (that needs
// the radar loop + KIS/Upbit market data wired end-to-end, which lands
// incrementally through later phases). Shows the card's real shape now
// rather than waiting until everything upstream of it is done.
const SAMPLE_RECOMMENDATION: Recommendation = {
  id: "sample-1",
  symbol: "KRW-XRP",
  asset_type: "CRYPTO",
  score: 92,
  state: "CONFIRMED_BREAKOUT",
  entry_low: 4080,
  entry_high: 4130,
  stop_price: 3980,
  t1_price: 4270,
  t1_percent: 30,
  t2_price: 4450,
  t2_percent: 30,
  runner_percent: 40,
  expected_max_loss: 9500,
  risk_reward: 2.1,
  reasons: [
    "Confirmed breakout above the opening range high",
    "RVOL 2.4x average volume",
    "Outperforming the benchmark by 3.2%",
  ],
  risks: ["Standard breakout risk: the level can fail after triggering (failed breakout)"],
  created_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 150_000).toISOString(),
};

function App() {
  const [systemStatus, setSystemStatus] = useState<SystemStatus>("checking");
  const approvalToken = matchApprovalRoute(window.location.pathname);

  useEffect(() => {
    let cancelled = false;

    fetchReadiness()
      .then((res) => {
        if (!cancelled) setSystemStatus(res.status === "ready" ? "정상" : "점검필요");
      })
      .catch(() => {
        if (!cancelled) setSystemStatus("점검필요");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (approvalToken) {
    return <ApprovalPage token={approvalToken} userId={currentUserId()} />;
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <h1>Multi Asset Radar</h1>
        <span className={`status-badge status-${systemStatus === "정상" ? "ok" : "warn"}`}>
          SYSTEM ● {systemStatus === "checking" ? "확인 중" : systemStatus}
        </span>
      </header>

      <section className="card">
        <div className="card-row">
          <span>국내시장</span>
          <span className="muted">데이터 대기</span>
        </div>
        <div className="card-row">
          <span>BTC</span>
          <span className="muted">데이터 대기</span>
        </div>
      </section>

      <section className="card">
        <p className="card-title">승인 대기 0건</p>
        <button type="button" className="cta" disabled>
          지금 확인
        </button>
      </section>

      <section className="card">
        <p className="card-title">보유종목 0</p>
        <p className="muted">오늘 손익 —</p>
        <p className="muted">위험사용 0 / 1.5%</p>
      </section>

      <section>
        <p className="card-title">TOP 추천</p>
        <RecommendationCard recommendation={SAMPLE_RECOMMENDATION} />
      </section>
    </main>
  );
}

export default App;
