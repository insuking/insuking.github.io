import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import { ApprovalApiError } from "../api/client";
import type { ApprovalDetail } from "../types/approval";
import { ApprovalPage } from "./ApprovalPage";

function buildDetail(overrides: Partial<ApprovalDetail> = {}): ApprovalDetail {
  return {
    approval_state: "OPENED",
    remaining_seconds: 150,
    symbol: "KRW-XRP",
    asset_type: "CRYPTO",
    entry_low: 4080,
    entry_high: 4130,
    stop_price: 3980,
    t1_price: 4270,
    t1_percent: 30,
    t2_price: 4450,
    t2_percent: 30,
    runner_percent: 40,
    expected_max_loss: 9500,
    risk_reward: 2.1,
    score: 92,
    confidence: "HIGH",
    reasons: ["Confirmed breakout above the opening range high"],
    risks: ["Standard breakout risk"],
    ...overrides,
  };
}

describe("ApprovalPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a login notice when no user is authenticated", () => {
    render(<ApprovalPage token="tok-1" userId={null} />);
    expect(screen.getByText("카카오 로그인이 필요합니다.")).toBeInTheDocument();
  });

  it("renders approval detail once loaded", async () => {
    vi.spyOn(client, "fetchApproval").mockResolvedValue(buildDetail());

    render(<ApprovalPage token="tok-1" userId="user-1" />);

    await waitFor(() => expect(screen.getByTestId("approval-page")).toBeInTheDocument());

    expect(screen.getByText("KRW-XRP")).toBeInTheDocument();
    expect(screen.getByText(/₩4,080/)).toBeInTheDocument();
    expect(screen.getByText("92 / HIGH")).toBeInTheDocument();
    expect(screen.getByText("Confirmed breakout above the opening range high")).toBeInTheDocument();
  });

  it("shows the load error when the fetch fails", async () => {
    vi.spyOn(client, "fetchApproval").mockRejectedValue(new ApprovalApiError(404, "찾을 수 없음"));

    render(<ApprovalPage token="tok-1" userId="user-1" />);

    await waitFor(() => expect(screen.getByText("찾을 수 없음")).toBeInTheDocument());
  });

  it("submits a HOLD decision without requiring a PIN", async () => {
    vi.spyOn(client, "fetchApproval").mockResolvedValue(buildDetail());
    const decideSpy = vi
      .spyOn(client, "decideApproval")
      .mockResolvedValue({ approval_state: "OPENED" });

    render(<ApprovalPage token="tok-1" userId="user-1" />);
    await waitFor(() => expect(screen.getByTestId("approval-page")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "보류" }));

    await waitFor(() => expect(decideSpy).toHaveBeenCalledWith("tok-1", "user-1", { decision: "HOLD" }));
  });

  it("requires a PIN before approving, then submits it", async () => {
    vi.spyOn(client, "fetchApproval").mockResolvedValue(buildDetail());
    const decideSpy = vi
      .spyOn(client, "decideApproval")
      .mockResolvedValue({ approval_state: "APPROVED" });

    render(<ApprovalPage token="tok-1" userId="user-1" />);
    await waitFor(() => expect(screen.getByTestId("approval-page")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "승인" }));
    expect(decideSpy).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText("PIN"), { target: { value: "1234" } });
    fireEvent.click(screen.getByRole("button", { name: "확인" }));

    await waitFor(() =>
      expect(decideSpy).toHaveBeenCalledWith("tok-1", "user-1", { decision: "APPROVE", pin: "1234" }),
    );
    await waitFor(() => expect(screen.getByText("승인 완료")).toBeInTheDocument());
  });

  it("shows an error message when the PIN is rejected", async () => {
    vi.spyOn(client, "fetchApproval").mockResolvedValue(buildDetail());
    vi.spyOn(client, "decideApproval").mockRejectedValue(new ApprovalApiError(400, "PIN이 올바르지 않습니다"));

    render(<ApprovalPage token="tok-1" userId="user-1" />);
    await waitFor(() => expect(screen.getByTestId("approval-page")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "승인" }));
    fireEvent.change(screen.getByPlaceholderText("PIN"), { target: { value: "0000" } });
    fireEvent.click(screen.getByRole("button", { name: "확인" }));

    await waitFor(() => expect(screen.getByText("PIN이 올바르지 않습니다")).toBeInTheDocument());
  });

  it("disables decision buttons once the approval reaches a terminal state", async () => {
    vi.spyOn(client, "fetchApproval").mockResolvedValue(buildDetail({ approval_state: "REJECTED" }));

    render(<ApprovalPage token="tok-1" userId="user-1" />);
    await waitFor(() => expect(screen.getByTestId("approval-page")).toBeInTheDocument());

    expect(screen.getByRole("button", { name: "승인" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "거절" })).toBeDisabled();
    expect(screen.getByText("거절됨")).toBeInTheDocument();
  });

  it("disables decision buttons once already expired", async () => {
    vi.spyOn(client, "fetchApproval").mockResolvedValue(buildDetail({ remaining_seconds: 0 }));

    render(<ApprovalPage token="tok-1" userId="user-1" />);
    await waitFor(() => expect(screen.getByTestId("approval-page")).toBeInTheDocument());

    expect(screen.getByRole("button", { name: "승인" })).toBeDisabled();
    expect(screen.getByText("만료됨")).toBeInTheDocument();
  });
});
