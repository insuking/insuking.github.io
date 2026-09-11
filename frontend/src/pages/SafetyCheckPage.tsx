import { useEffect, useState } from "react";
import { fetchSafetyCheck } from "../api/client";
import type { SafetyCheck, SafetyCheckItem } from "../types/account";
import "./SafetyCheckPage.css";

interface SafetyCheckPageProps {
  onContinue: () => void;
}

const STATUS_ICON: Record<SafetyCheckItem["status"], string> = {
  ok: "✓",
  warning: "!",
  manual_check: "?",
};

const STATUS_LABEL: Record<SafetyCheckItem["status"], string> = {
  ok: "확인 완료",
  warning: "확인 필요",
  manual_check: "수동 확인 필요",
};

/**
 * "시작 안전점검" onboarding gate (P45) - shown once per browser
 * (`localStorage`'s `safetyCheckPassed` flag, set by `App.tsx` on
 * "안전하게 시작하기") before the six main tabs. Every item here is a
 * real signal from `GET /api/dashboard/safety-check` - never a hardcoded
 * green row. "실거래 모드로 전환" is deliberately not a working toggle:
 * `LIVE_TRADING` is a server-side deployment setting
 * (docker-compose.yml/.env), not something this project lets a UI
 * button flip - the whole point of that default-off switch is that it
 * takes a deliberate infrastructure change, not an in-app tap, to ever
 * risk real money.
 */
export function SafetyCheckPage({ onContinue }: SafetyCheckPageProps) {
  const [check, setCheck] = useState<SafetyCheck | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchSafetyCheck()
      .then((result) => {
        if (!cancelled) setCheck(result);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const okCount = check?.items.filter((item) => item.status === "ok").length ?? 0;
  const total = check?.items.length ?? 5;
  const progressPct = check ? (okCount / total) * 100 : 0;
  const demoItem = check?.items.find((item) => item.key === "demo_mode");

  return (
    <main className="page safety-check-page">
      <header className="app-header">
        <h1>시작 안전점검</h1>
      </header>

      {demoItem && (
        <section className={`card safety-banner safety-banner--${demoItem.status === "ok" ? "demo" : "live"}`}>
          <span className="safety-banner__badge">{demoItem.status === "ok" ? "DEMO" : "LIVE"}</span>
          <div>
            <p className="card-title">{demoItem.label}</p>
            <p className="muted small">{demoItem.detail}</p>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-row">
          <p className="card-title" style={{ margin: 0 }}>
            안전점검 항목
          </p>
          <span className="muted small">
            {okCount} / {total} 완료
          </span>
        </div>
        <div className="safety-progress">
          <div className="safety-progress__fill" style={{ width: `${progressPct}%` }} />
        </div>

        {check === null && !loadError && <p className="muted">확인 중...</p>}
        {loadError && (
          <>
            <p className="muted">안전점검 정보를 불러오지 못했습니다.</p>
            <button
              type="button"
              className="retry-button"
              onClick={() => {
                setLoadError(false);
                setCheck(null);
                fetchSafetyCheck()
                  .then(setCheck)
                  .catch(() => setLoadError(true));
              }}
            >
              다시 시도
            </button>
          </>
        )}

        {check?.items.map((item) => (
          <div className="safety-item" key={item.key}>
            <span className={`safety-item__icon safety-item__icon--${item.status}`}>
              {STATUS_ICON[item.status]}
            </span>
            <div className="safety-item__body">
              <div className="card-row" style={{ padding: 0 }}>
                <span className="safety-item__label">{item.label}</span>
                <span className={`safety-item__status safety-item__status--${item.status}`}>
                  {STATUS_LABEL[item.status]}
                </span>
              </div>
              <p className="muted small">{item.detail}</p>
            </div>
          </div>
        ))}
      </section>

      <button type="button" className="cta safety-start-cta" disabled={!check?.all_ok} onClick={onContinue}>
        안전하게 시작하기
      </button>
      <button type="button" className="safety-live-toggle" disabled>
        실거래 모드로 전환
        <span className="muted small">LIVE_TRADING은 서버 설정(.env)에서만 변경할 수 있습니다.</span>
      </button>
    </main>
  );
}
