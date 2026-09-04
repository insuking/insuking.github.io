import { useEffect, useState } from "react";
import { fetchReadiness } from "./api/client";
import "./App.css";

type SystemStatus = "checking" | "정상" | "점검필요";

function App() {
  const [systemStatus, setSystemStatus] = useState<SystemStatus>("checking");

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

      <section className="card">
        <p className="card-title">TOP 추천</p>
        <p className="muted">아직 감지된 후보가 없습니다.</p>
      </section>
    </main>
  );
}

export default App;
