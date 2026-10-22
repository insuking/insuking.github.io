import { useEffect, useState, type ComponentType } from "react";
import { ApprovalPage } from "./components/ApprovalPage";
import { NavBar } from "./components/NavBar";
import { currentUserId } from "./auth";
import { tabFromHash, type TabId } from "./nav";
import { EmergencyStopPage } from "./pages/EmergencyStopPage";
import { HomePage } from "./pages/HomePage";
import { KakaoCallbackPage } from "./pages/KakaoCallbackPage";
import { MarketPage } from "./pages/MarketPage";
import { PerformancePage } from "./pages/PerformancePage";
import { PositionDetailPage } from "./pages/PositionDetailPage";
import { PositionsPage } from "./pages/PositionsPage";
import { RecommendationsPage } from "./pages/RecommendationsPage";
import { SafetyCheckPage } from "./pages/SafetyCheckPage";
import { StockRadarPage } from "./pages/StockRadarPage";
import { SystemPage } from "./pages/SystemPage";
import "./App.css";

// P45 "시작 안전점검" onboarding gate - shown once per browser until the
// user taps through it (same localStorage-flag pattern as auth.ts's
// userId), never re-shown automatically on every load. A deep link
// (approval page, Kakao callback) bypasses it entirely - see below.
const SAFETY_CHECK_STORAGE_KEY = "safetyCheckPassed";

function hasPassedSafetyCheck(): boolean {
  try {
    return localStorage.getItem(SAFETY_CHECK_STORAGE_KEY) === "true";
  } catch {
    return true; // storage unavailable - don't block the app on it
  }
}

function markSafetyCheckPassed(): void {
  try {
    localStorage.setItem(SAFETY_CHECK_STORAGE_KEY, "true");
  } catch {
    // ignore - private browsing / quota, same as auth.ts's setUserId
  }
}

// No router dependency - two pathname-based deep links (the Kakao "send to
// me" approval link and the Kakao OAuth redirect) plus a hash-based tab bar
// for the six flat P21 nav tabs (see nav.ts) covers this app's whole route
// surface without pulling in react-router.
function matchApprovalRoute(pathname: string): string | null {
  const match = /^\/approve\/([^/]+)$/.exec(pathname);
  return match ? match[1] : null;
}

function isKakaoCallbackRoute(pathname: string): boolean {
  return pathname === "/auth/kakao/callback";
}

// A small, deliberate nested extension of the same hash scheme (see
// nav.ts's own docstring on "#/positions etc." giving real back-button/
// bookmark support without react-router) - `#/positions/:id` is an 8th
// route this project's seven flat tabs never needed before P46's position
// detail screen. `tabFromHash()` only matches the seven exact tab hashes,
// so this is checked separately, before falling through to the tab pages.
function matchPositionDetailRoute(hash: string): string | null {
  const match = /^#\/positions\/([^/]+)$/.exec(hash);
  return match ? decodeURIComponent(match[1]) : null;
}

function isEmergencyStopRoute(hash: string): boolean {
  return hash === "#/emergency";
}

const TAB_PAGES: Record<TabId, ComponentType> = {
  radar: HomePage,
  stocks: StockRadarPage,
  recommendations: RecommendationsPage,
  positions: PositionsPage,
  market: MarketPage,
  performance: PerformancePage,
  system: SystemPage,
};

function App() {
  const [hash, setHash] = useState<string>(() => window.location.hash);
  const [safetyCheckPassed, setSafetyCheckPassed] = useState(hasPassedSafetyCheck);

  useEffect(() => {
    function onHashChange() {
      setHash(window.location.hash);
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const approvalToken = matchApprovalRoute(window.location.pathname);
  if (approvalToken) {
    return <ApprovalPage token={approvalToken} userId={currentUserId()} />;
  }

  if (isKakaoCallbackRoute(window.location.pathname)) {
    return <KakaoCallbackPage />;
  }

  if (!safetyCheckPassed) {
    return (
      <div className="app-shell">
        <SafetyCheckPage
          onContinue={() => {
            markSafetyCheckPassed();
            setSafetyCheckPassed(true);
          }}
        />
      </div>
    );
  }

  const positionDetailId = matchPositionDetailRoute(hash);
  const tab = tabFromHash(hash);

  if (positionDetailId) {
    return (
      <div className="app-shell">
        <PositionDetailPage positionId={positionDetailId} />
        <NavBar active="positions" />
      </div>
    );
  }

  if (isEmergencyStopRoute(hash)) {
    return (
      <div className="app-shell">
        <EmergencyStopPage />
        <NavBar active="radar" />
      </div>
    );
  }

  const ActivePage = TAB_PAGES[tab];
  return (
    <div className="app-shell">
      <ActivePage />
      <NavBar active={tab} />
    </div>
  );
}

export default App;
