import { describe, expect, it } from "vitest";
import { TABS, tabFromHash } from "./nav";

describe("tabFromHash", () => {
  it("maps each tab's own hash back to its id", () => {
    for (const tab of TABS) {
      expect(tabFromHash(tab.hash)).toBe(tab.id);
    }
  });

  it("defaults to radar for an unknown or empty hash", () => {
    expect(tabFromHash("")).toBe("radar");
    expect(tabFromHash("#/does-not-exist")).toBe("radar");
  });
});
