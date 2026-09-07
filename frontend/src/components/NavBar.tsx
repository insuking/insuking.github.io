import { TABS, type TabId } from "../nav";
import "./NavBar.css";

interface NavBarProps {
  active: TabId;
}

/**
 * Bottom tab bar (P21) - docs/MASTER_SPEC.md P21: "one-hand usability,
 * 44px minimum touch targets, never color-only signaling". Bottom
 * placement is the one-hand-reachable position on a tall phone; each tab
 * is a real `<a>` (not a click handler on a `<div>`) so the hash route is
 * bookmarkable/shareable and works with the browser back button for free.
 * The active tab is marked by a filled background AND `aria-current`, not
 * by color alone - a color-blind or low-vision reader still gets it from
 * the shape/weight change and a screen reader gets it from `aria-current`.
 */
export function NavBar({ active }: NavBarProps) {
  return (
    <nav className="nav-bar" aria-label="주요 메뉴">
      {TABS.map((tab) => {
        const isActive = tab.id === active;
        return (
          <a
            key={tab.id}
            href={tab.hash}
            className={`nav-bar__item${isActive ? " nav-bar__item--active" : ""}`}
            aria-current={isActive ? "page" : undefined}
          >
            {tab.label}
          </a>
        );
      })}
    </nav>
  );
}
