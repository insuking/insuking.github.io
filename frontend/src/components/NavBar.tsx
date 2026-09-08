import type { FC, SVGProps } from "react";
import { TABS, type TabId } from "../nav";
import "./NavBar.css";

interface NavBarProps {
  active: TabId;
}

type IconProps = SVGProps<SVGSVGElement>;

function RadarIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" {...props}>
      <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="1.8" fill="currentColor" />
      <path d="M12 12L18 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function StarIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" {...props}>
      <path
        d="M12 4.5l2.29 4.64 5.12.74-3.7 3.61.87 5.1L12 16.1l-4.58 2.41.87-5.1-3.7-3.6 5.12-.75L12 4.5z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function WalletIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" {...props}>
      <rect x="3.5" y="6" width="17" height="13" rx="2.5" stroke="currentColor" strokeWidth="1.8" />
      <path d="M3.5 10h17" stroke="currentColor" strokeWidth="1.8" />
      <path d="M15 13.5h2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function ChartIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" {...props}>
      <path
        d="M4 19V10.5M10 19V5M16 19v-6.5M20 19H4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TrendingIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" {...props}>
      <path
        d="M4 16l5.2-5.5 3.6 3.2L20 6.5M20 6.5h-4.5M20 6.5V11"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function GearIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" {...props}>
      <circle cx="12" cy="12" r="3.2" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M12 3.5v2.3M12 18.2v2.3M20.5 12h-2.3M5.8 12H3.5M17.7 6.3l-1.6 1.6M7.9 16.1l-1.6 1.6M17.7 17.7l-1.6-1.6M7.9 7.9 6.3 6.3"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

const TAB_ICON: Record<TabId, FC<IconProps>> = {
  radar: RadarIcon,
  recommendations: StarIcon,
  positions: WalletIcon,
  market: ChartIcon,
  performance: TrendingIcon,
  system: GearIcon,
};

/**
 * Bottom tab bar (P21) - docs/MASTER_SPEC.md P21: "one-hand usability,
 * 44px minimum touch targets, never color-only signaling". Bottom
 * placement is the one-hand-reachable position on a tall phone; each tab
 * is a real `<a>` (not a click handler on a `<div>`) so the hash route is
 * bookmarkable/shareable and works with the browser back button for free.
 * The active tab is marked by a filled icon/label color AND `aria-current`
 * AND bolder label weight, not by color alone - a color-blind or
 * low-vision reader still gets it from the weight change and a screen
 * reader gets it from `aria-current`.
 */
export function NavBar({ active }: NavBarProps) {
  return (
    <nav className="nav-bar" aria-label="주요 메뉴">
      {TABS.map((tab) => {
        const isActive = tab.id === active;
        const Icon = TAB_ICON[tab.id];
        return (
          <a
            key={tab.id}
            href={tab.hash}
            className={`nav-bar__item${isActive ? " nav-bar__item--active" : ""}`}
            aria-current={isActive ? "page" : undefined}
          >
            <Icon className="nav-bar__icon" aria-hidden="true" />
            <span className="nav-bar__label">{tab.label}</span>
          </a>
        );
      })}
    </nav>
  );
}
