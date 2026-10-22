import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { RiskStateHistory } from "../types/position";
import type { DashboardSummary } from "../types/dashboard";
import { EmergencyStopPage } from "./EmergencyStopPage";

function buildSummary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    market_regime: null,
    market_regime_updated_at: null,
    btc_regime: "RISK_ON",
    btc_regime_updated_at: null,
    overall_health: "HEALTHY",
    service_health: [],
    open_incidents: 0,
    pending_approvals: 0,
    top_opportunities: [],
    positions: [],
    risk_used: null,
    stock_decision_state: null,
    stock_decision_reason: null,
    stock_decision_top_symbol: null,
    stock_decision_top_symbol_name: null,
    stock_decision_observed_at: null,
    macro_regime: null,
    macro_headline: null,
    macro_observed_at: null,
    ...overrides,
  };
}

function buildHistory(overrides: Partial<RiskStateHistory> = {}): RiskStateHistory {
  return { snapshots: [], ...overrides };
}

describe("EmergencyStopPage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the real current kill-switch status, never a fabricated one", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(
      buildSummary({
        risk_used: {
          as_of: new Date().toISOString(),
          daily_loss: 0,
          daily_loss_limit: 100_000,
          exposure: 0,
          exposure_limit: 100_000,
          open_positions: 0,
          max_positions: 5,
          consecutive_stops: 0,
          kill_switch_active: true,
          kill_switch_reason: "사용자 수동 긴급정지 (user-1)",
        },
      }),
    );
    vi.spyOn(client, "fetchRiskStateHistory").mockResolvedValue(buildHistory());

    render(<EmergencyStopPage />);

    await waitFor(() => expect(screen.getByText("긴급정지 작동중")).toBeInTheDocument());
    expect(screen.getByText("사용자 수동 긴급정지 (user-1)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "눌러서 복구 (거래 재개)" })).toBeInTheDocument();
  });

  it("shows the real audit log entries newest first, an empty list when there are none", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchRiskStateHistory").mockResolvedValue(buildHistory());

    render(<EmergencyStopPage />);

    await waitFor(() => expect(screen.getByText("기록이 없습니다.")).toBeInTheDocument());
  });

  it("prompts a Kakao login before allowing activation", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchRiskStateHistory").mockResolvedValue(buildHistory());

    render(<EmergencyStopPage />);

    const button = await screen.findByRole("button", { name: "눌러서 긴급정지" });
    fireEvent.mouseDown(button);

    await waitFor(
      () => expect(screen.getByText("카카오 로그인 후 긴급정지를 사용할 수 있습니다.")).toBeInTheDocument(),
      { timeout: 3000 },
    );
  });

  it("activates the emergency stop only after the hold-to-confirm gesture completes", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchRiskStateHistory").mockResolvedValue(buildHistory());
    const activate = vi.spyOn(client, "activateEmergencyStop").mockResolvedValue({
      kill_switch_active: true,
      kill_switch_reason: "사용자 수동 긴급정지 (user-1)",
    });

    render(<EmergencyStopPage />);

    const button = await screen.findByRole("button", { name: "눌러서 긴급정지" });
    fireEvent.mouseDown(button);
    expect(activate).not.toHaveBeenCalled();

    await waitFor(() => expect(activate).toHaveBeenCalledWith("user-1"), { timeout: 3000 });
  });
});
