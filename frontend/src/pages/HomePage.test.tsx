import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { Balance, BalanceHistory } from "../types/account";
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

function buildBalance(overrides: Partial<Balance> = {}): Balance {
  return {
    kis_total_value: null,
    upbit_total_value: null,
    total_assets: 0,
    ...overrides,
  };
}

function buildHistory(overrides: Partial<BalanceHistory> = {}): BalanceHistory {
  return {
    window: "1d",
    snapshots: [],
    ...overrides,
  };
}

function mockAccountEndpoints() {
  vi.spyOn(client, "fetchBalance").mockResolvedValue(buildBalance());
  vi.spyOn(client, "fetchBalanceHistory").mockResolvedValue(buildHistory());
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
    mockAccountEndpoints();

    render(<HomePage />);

    expect(screen.getByText("카카오 로그인이 필요합니다")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "카카오 로그인" })).toBeInTheDocument();
  });

  it("hides the login prompt once a user id is stored", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    mockAccountEndpoints();

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
    mockAccountEndpoints();

    render(<HomePage />);

    await waitFor(() => expect(screen.getByText("승인 대기 3건")).toBeInTheDocument());
    expect(screen.getAllByText("1,000").length).toBeGreaterThan(0); // 오늘 손실 stat card
    expect(screen.getAllByText("99,000").length).toBeGreaterThan(0); // 남은 손실한도 stat card
  });

  it("shows a load error when the summary fetch fails", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchDashboardSummary").mockRejectedValue(new Error("network down"));
    mockAccountEndpoints();

    render(<HomePage />);

    await waitFor(() => expect(screen.getByText("데이터를 불러오지 못했습니다.")).toBeInTheDocument());
  });

  it("shows a friendly error if the Kakao login redirect can't start", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchKakaoLoginUrl").mockRejectedValue(
      new client.ApprovalApiError(503, "KAKAO_CLIENT_ID not set"),
    );
    mockAccountEndpoints();

    render(<HomePage />);
    screen.getByRole("button", { name: "카카오 로그인" }).click();

    await waitFor(() =>
      expect(
        screen.getByText("카카오 로그인을 시작할 수 없습니다. 잠시 후 다시 시도해주세요."),
      ).toBeInTheDocument(),
    );
  });

  it("shows the real combined total assets once the balance loads", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchBalance").mockResolvedValue(
      buildBalance({ kis_total_value: 1_000_000, upbit_total_value: 500_000, total_assets: 1_500_000 }),
    );
    vi.spyOn(client, "fetchBalanceHistory").mockResolvedValue(buildHistory());

    render(<HomePage />);

    await waitFor(() => expect(screen.getByText("1,500,000")).toBeInTheDocument());
  });

  it("prompts a Kakao login before allowing an emergency stop", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    mockAccountEndpoints();

    render(<HomePage />);
    screen.getByRole("button", { name: "긴급정지" }).click();

    await waitFor(() =>
      expect(screen.getByText("카카오 로그인 후 긴급정지를 사용할 수 있습니다.")).toBeInTheDocument(),
    );
  });

  it("activates the emergency stop for a logged-in user", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "activateEmergencyStop").mockResolvedValue({
      kill_switch_active: true,
      kill_switch_reason: "사용자 수동 긴급정지 (user-1)",
    });
    mockAccountEndpoints();

    render(<HomePage />);
    screen.getByRole("button", { name: "긴급정지" }).click();

    await waitFor(() =>
      expect(screen.getByText("긴급정지가 활성화되었습니다. 새로운 거래가 차단됩니다.")).toBeInTheDocument(),
    );
  });
});
