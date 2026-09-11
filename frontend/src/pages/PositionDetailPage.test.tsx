import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { PositionDetail } from "../types/position";
import { PositionDetailPage } from "./PositionDetailPage";

function buildDetail(overrides: Partial<PositionDetail> = {}): PositionDetail {
  return {
    id: "pos-1",
    symbol: "KRW-BTC",
    asset_type: "CRYPTO",
    state: "T1_FILLED",
    quantity: 0.5,
    avg_entry_price: 100_000_000,
    stop_price: 95_000_000,
    guardian_active: true,
    opened_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    current_price: 105_000_000,
    unrealized_pnl: 2_500_000,
    unrealized_pnl_pct: 5.0,
    protective_orders: [
      { kind: "STOP", trigger_price: 95_000_000, quantity: 0.5, active: true },
      { kind: "T1", trigger_price: 110_000_000, quantity: 0.15, active: true },
    ],
    ...overrides,
  };
}

describe("PositionDetailPage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the real fill-derived state and protective order targets", async () => {
    vi.spyOn(client, "fetchPositionDetail").mockResolvedValue(buildDetail());

    render(<PositionDetailPage positionId="pos-1" />);

    await waitFor(() => expect(screen.getByText("T1 체결")).toBeInTheDocument());
    expect(screen.getByText("손절가")).toBeInTheDocument();
    expect(screen.getByText("T1 목표가")).toBeInTheDocument();
  });

  it("prompts a Kakao login before allowing a guardian pause", async () => {
    vi.spyOn(client, "fetchPositionDetail").mockResolvedValue(buildDetail());

    render(<PositionDetailPage positionId="pos-1" />);

    await waitFor(() => expect(screen.getByText("자동관리 일시정지")).toBeInTheDocument());
    fireEvent.click(screen.getByText("자동관리 일시정지"));

    await waitFor(() =>
      expect(screen.getByText("카카오 로그인 후 이용할 수 있습니다.")).toBeInTheDocument(),
    );
  });

  it("pauses guardian for a logged-in user", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchPositionDetail").mockResolvedValue(buildDetail());
    const toggle = vi.spyOn(client, "setPositionGuardianActive").mockResolvedValue({
      id: "pos-1",
      guardian_active: false,
    });

    render(<PositionDetailPage positionId="pos-1" />);

    await waitFor(() => expect(screen.getByText("자동관리 일시정지")).toBeInTheDocument());
    fireEvent.click(screen.getByText("자동관리 일시정지"));

    await waitFor(() => expect(toggle).toHaveBeenCalledWith("pos-1", "user-1", false));
  });

  it("closes the position only after the hold-to-confirm gesture completes", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchPositionDetail").mockResolvedValue(buildDetail());
    const close = vi.spyOn(client, "closePosition").mockResolvedValue({
      id: "pos-1",
      state: "CLOSED",
      order_id: "order-1",
      order_status: "SUBMITTED",
    });

    render(<PositionDetailPage positionId="pos-1" />);

    const button = await screen.findByRole("button", { name: "눌러서 즉시 청산" });
    fireEvent.mouseDown(button);
    expect(close).not.toHaveBeenCalled();

    await waitFor(() => expect(close).toHaveBeenCalledWith("pos-1", "user-1"), { timeout: 3000 });
    await waitFor(() => expect(screen.getByText("청산 주문이 접수되었습니다.")).toBeInTheDocument());
  });

  it("never fabricates a closed state when the close request fails (e.g. demo mode)", async () => {
    localStorage.setItem("userId", "user-1");
    vi.spyOn(client, "fetchPositionDetail").mockResolvedValue(buildDetail());
    vi.spyOn(client, "closePosition").mockRejectedValue(
      new client.ApprovalApiError(409, "LIVE_TRADING이 비활성화되어 있어 실거래 주문을 낼 수 없습니다 (데모 모드)."),
    );

    render(<PositionDetailPage positionId="pos-1" />);

    const button = await screen.findByRole("button", { name: "눌러서 즉시 청산" });
    fireEvent.mouseDown(button);

    await waitFor(
      () =>
        expect(
          screen.getByText("LIVE_TRADING이 비활성화되어 있어 실거래 주문을 낼 수 없습니다 (데모 모드)."),
        ).toBeInTheDocument(),
      { timeout: 3000 },
    );
  });
});
