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

  it("disables the start button when a blocking item (demo_mode/kill_switch) isn't ok", async () => {
    vi.spyOn(client, "fetchSafetyCheck").mockResolvedValue(
      buildCheck({
        items: [
          { key: "demo_mode", label: "Demo 모드", status: "ok", detail: "데모 환경" },
          { key: "kill_switch", label: "긴급정지 점검 완료", status: "warning", detail: "저장소 접근 실패" },
        ],
        all_ok: false,
      }),
    );

    render(<SafetyCheckPage onContinue={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("확인 필요")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "안전하게 시작하기" })).toBeDisabled();
  });

  it("enables the start button even when a non-blocking item (exchange_connection/daily_loss_limit) isn't ok", async () => {
    // The P46 regression this guards: a fresh local deployment with no
    // broker keys configured yet, or before the scheduler's first cycle,
    // would otherwise show a permanent "확인 필요" on these two and never
    // let anyone past this screen - even though nothing dangerous is
    // happening and this screen has no effect on LIVE_TRADING either way.
    vi.spyOn(client, "fetchSafetyCheck").mockResolvedValue(
      buildCheck({
        items: [
          { key: "demo_mode", label: "Demo 모드", status: "ok", detail: "데모 환경" },
          { key: "exchange_connection", label: "거래소 연결 정상", status: "warning", detail: "KIS 미설정 · Upbit 연결 실패" },
          { key: "withdrawal_disabled", label: "출금 권한 비활성", status: "ok", detail: "출금 API 없음" },
          { key: "daily_loss_limit", label: "오늘 최대손실 한도", status: "warning", detail: "아직 기록 없음" },
          { key: "kill_switch", label: "긴급정지 점검 완료", status: "ok", detail: "정상" },
        ],
        all_ok: false,
      }),
    );

    render(<SafetyCheckPage onContinue={vi.fn()} />);

    await waitFor(() => expect(screen.getAllByText("확인 필요")).toHaveLength(2));
    expect(screen.getByRole("button", { name: "안전하게 시작하기" })).not.toBeDisabled();
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
