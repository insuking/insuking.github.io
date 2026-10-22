/**
 * Tab navigation (P21, extended in P28). Originally docs/MASTER_SPEC.md
 * P21's six flat tabs: "Radar / 추천 / 포지션 / 시장 / 성과 / 시스템" -
 * `stocks` (종목레이더) is a P28 addition, since the stock radar (P23+)
 * postdates that original list and produces its own kind of candidate
 * (`PreBreakoutScore`, a ranking signal) rather than the `Recommendation`
 * (entry/stop/target trade plan) the existing 추천 tab shows - see
 * `StockRadarPage.tsx`'s own docstring for why those stay separate tabs.
 * Hash-based rather than a router dependency (see App.tsx's existing
 * comment on `/approve/:token` for why this project has stayed
 * dependency-free here) - `#/positions` etc. still gives real
 * back-button/bookmark support without pulling in react-router for seven
 * flat, non-nested routes.
 *
 * `stocks`'s label is "종목", not the page's own full "종목레이더" title -
 * every other tab label is 2-3 Korean characters, and the full 5-character
 * name wrapped onto two lines at this bar's per-tab width (7 tabs, not the
 * original 6 the P21 layout was sized for), breaking the single-row rhythm
 * every other tab keeps. `StockRadarPage.tsx`'s `<h1>` still says
 * "종목레이더" in full - only this cramped nav slot needed shortening.
 */

export const TABS = [
  { id: "radar", label: "Radar", hash: "#/radar" },
  { id: "stocks", label: "종목", hash: "#/stocks" },
  { id: "recommendations", label: "추천", hash: "#/recommendations" },
  { id: "positions", label: "포지션", hash: "#/positions" },
  { id: "market", label: "시장", hash: "#/market" },
  { id: "performance", label: "성과", hash: "#/performance" },
  { id: "system", label: "시스템", hash: "#/system" },
] as const;

export type TabId = (typeof TABS)[number]["id"];

const DEFAULT_TAB: TabId = "radar";

export function tabFromHash(hash: string): TabId {
  const found = TABS.find((tab) => tab.hash === hash);
  return found ? found.id : DEFAULT_TAB;
}
