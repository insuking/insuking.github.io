import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { DashboardSummary } from "../types/dashboard";
import { HomePage } from "./HomePage";

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

describe("HomePage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the Kakao login prompt when no user is stored", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());

    render(<HomePage />);

    expect(screen.getByText("카카오 로그인이 필요합니다")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "카카오 로그인" })).toBeInTheDocument();
  });

  it("hides the login prompt once a user id is stored", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());

    render(<HomePage />);

    expect(screen.queryByText("카카오 로그인이 필요합니다")).not.toBeInTheDocument();
  });

  it("renders real regime/health/risk data once loaded, never sample data", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(
      buildSummary({
        btc_regime: "RISK_OFF",
        pending_approvals: 3,
        risk_used: {
          as_of: new Date().toISOString(),
          daily_loss: 1000,
          daily_loss_limit: 100000,
          exposure: 25000,
          exposure_limit: 100000,
          open_positions: 1,
          max_positions: 5,
          consecutive_stops: 0,
          kill_switch_active: false,
          kill_switch_reason: null,
        },
      }),
    );

    render(<HomePage />);

    await waitFor(() => expect(screen.getByText("RISK_OFF")).toBeInTheDocument());
    expect(screen.getByText("승인 대기 3건")).toBeInTheDocument();
    expect(screen.getByText(/위험사용 25\.0%/)).toBeInTheDocument();
  });

  it("shows a load error when the summary fetch fails", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchDashboardSummary").mockRejectedValue(new Error("network down"));

    render(<HomePage />);

    await waitFor(() => expect(screen.getByText("데이터를 불러오지 못했습니다.")).toBeInTheDocument());
  });

  it("shows a friendly error if the Kakao login redirect can't start", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchKakaoLoginUrl").mockRejectedValue(
      new client.ApprovalApiError(503, "KAKAO_CLIENT_ID not set"),
    );

    render(<HomePage />);
    screen.getByRole("button", { name: "카카오 로그인" }).click();

    await waitFor(() =>
      expect(
        screen.getByText("카카오 로그인을 시작할 수 없습니다. 잠시 후 다시 시도해주세요."),
      ).toBeInTheDocument(),
    );
  });
});
