import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { SafetyCheck } from "../types/account";
import { SafetyCheckPage } from "./SafetyCheckPage";

function buildCheck(overrides: Partial<SafetyCheck> = {}): SafetyCheck {
  return {
    items: [
      { key: "demo_mode", label: "Demo 모드", status: "ok", detail: "데모 환경" },
      { key: "exchange_connection", label: "거래소 연결 정상", status: "ok", detail: "정상" },
      { key: "withdrawal_disabled", label: "출금 권한 비활성", status: "ok", detail: "출금 API 없음" },
      { key: "daily_loss_limit", label: "오늘 최대손실 한도", status: "ok", detail: "설정됨" },
      { key: "kill_switch", label: "긴급정지 점검 완료", status: "ok", detail: "정상" },
    ],
    all_ok: true,
    ...overrides,
  };
}

describe("SafetyCheckPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("disables the start button until every real item is ok", async () => {
    vi.spyOn(client, "fetchSafetyCheck").mockResolvedValue(
      buildCheck({
        items: [
          { key: "demo_mode", label: "Demo 모드", status: "ok", detail: "데모 환경" },
          { key: "daily_loss_limit", label: "오늘 최대손실 한도", status: "warning", detail: "아직 기록 없음" },
        ],
        all_ok: false,
      }),
    );

    render(<SafetyCheckPage onContinue={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("확인 필요")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "안전하게 시작하기" })).toBeDisabled();
  });

  it("enables the start button and calls onContinue once every item is real and ok", async () => {
    vi.spyOn(client, "fetchSafetyCheck").mockResolvedValue(buildCheck());
    const onContinue = vi.fn();

    render(<SafetyCheckPage onContinue={onContinue} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "안전하게 시작하기" })).not.toBeDisabled());
    screen.getByRole("button", { name: "안전하게 시작하기" }).click();

    expect(onContinue).toHaveBeenCalledOnce();
  });

  it("never fabricates a passing checklist when the fetch fails", async () => {
    vi.spyOn(client, "fetchSafetyCheck").mockRejectedValue(new Error("network down"));

    render(<SafetyCheckPage onContinue={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("안전점검 정보를 불러오지 못했습니다.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "안전하게 시작하기" })).toBeDisabled();
  });

  it("shows the real-trading-mode-is-server-only note on the disabled live toggle", async () => {
    vi.spyOn(client, "fetchSafetyCheck").mockResolvedValue(buildCheck());

    render(<SafetyCheckPage onContinue={vi.fn()} />);

    expect(screen.getByRole("button", { name: /실거래 모드로 전환/ })).toBeDisabled();
    expect(screen.getByText(/LIVE_TRADING은 서버 설정/)).toBeInTheDocument();
  });
});
