/**
 * Tab navigation (P21) - docs/MASTER_SPEC.md P21: "nav: Radar / 추천 /
 * 포지션 / 시장 / 성과 / 시스템". Hash-based rather than a router
 * dependency (see App.tsx's existing comment on `/approve/:token` for why
 * this project has stayed dependency-free here) - `#/positions` etc. still
 * gives real back-button/bookmark support without pulling in react-router
 * for six flat, non-nested routes.
 */

export const TABS = [
  { id: "radar", label: "Radar", hash: "#/radar" },
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
