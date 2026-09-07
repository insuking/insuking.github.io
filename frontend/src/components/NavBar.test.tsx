import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TABS } from "../nav";
import { NavBar } from "./NavBar";

describe("NavBar", () => {
  it("renders all six P21 tabs with 44px-minimum touch targets", () => {
    render(<NavBar active="radar" />);
    for (const tab of TABS) {
      const link = screen.getByRole("link", { name: tab.label });
      expect(link).toHaveAttribute("href", tab.hash);
    }
    expect(screen.getAllByRole("link")).toHaveLength(TABS.length);
  });

  it("marks only the active tab with aria-current, never color alone", () => {
    render(<NavBar active="positions" />);
    const active = screen.getByRole("link", { name: "포지션" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active.className).toContain("nav-bar__item--active");

    const inactive = screen.getByRole("link", { name: "추천" });
    expect(inactive).not.toHaveAttribute("aria-current");
  });
});
