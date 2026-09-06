import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Recommendation } from "../types/domain";
import { RecommendationCard } from "./RecommendationCard";

function buildRecommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  const now = new Date("2026-01-05T09:30:00Z");
  return {
    id: "rec-1",
    symbol: "KRW-XRP",
    asset_type: "CRYPTO",
    score: 92,
    state: "CONFIRMED_BREAKOUT",
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
    reasons: ["Confirmed breakout above the opening range high", "RVOL 2.5x average volume"],
    risks: ["Standard breakout risk: the level can fail after triggering"],
    created_at: now.toISOString(),
    expires_at: new Date(now.getTime() + 150_000).toISOString(), // +150s
    ...overrides,
  };
}

describe("RecommendationCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-05T09:30:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders symbol, state, score, entry/stop/T1/T2/runner", () => {
    render(<RecommendationCard recommendation={buildRecommendation()} />);

    expect(screen.getByText("KRW-XRP")).toBeInTheDocument();
    expect(screen.getByText("CONFIRMED_BREAKOUT")).toBeInTheDocument();
    expect(screen.getByText("Score 92")).toBeInTheDocument();
    expect(screen.getByText(/₩4,080/)).toBeInTheDocument();
    expect(screen.getByText(/₩3,980/)).toBeInTheDocument();
    expect(screen.getByText("₩4,270")).toBeInTheDocument();
    expect(screen.getByText("₩4,450")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
  });

  it("hides reasons/risks until the toggle is clicked", () => {
    render(<RecommendationCard recommendation={buildRecommendation()} />);

    expect(screen.queryByText("왜 추천?")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /위험요인/ }));

    expect(screen.getByText("왜 추천?")).toBeInTheDocument();
    expect(screen.getByText("RVOL 2.5x average volume")).toBeInTheDocument();
    expect(
      screen.getByText("Standard breakout risk: the level can fail after triggering"),
    ).toBeInTheDocument();
  });

  it("shows a live countdown that ticks down every second", () => {
    render(<RecommendationCard recommendation={buildRecommendation()} />);

    expect(screen.getByTestId("countdown")).toHaveTextContent("02:30");

    act(() => { vi.advanceTimersByTime(5000); });

    expect(screen.getByTestId("countdown")).toHaveTextContent("02:25");
  });

  it("disables the approve button once the recommendation expires", () => {
    const recommendation = buildRecommendation({
      expires_at: new Date("2026-01-05T09:30:03Z").toISOString(),
    });
    const onApprove = vi.fn();
    render(<RecommendationCard recommendation={recommendation} onApprove={onApprove} />);

    const button = screen.getByRole("button", { name: "승인하기" });
    expect(button).not.toBeDisabled();

    act(() => { vi.advanceTimersByTime(4000); });

    expect(button).toBeDisabled();
    expect(screen.getByTestId("countdown")).toHaveTextContent("만료됨");
  });

  it("calls onApprove when the CTA is clicked", () => {
    const onApprove = vi.fn();
    render(<RecommendationCard recommendation={buildRecommendation()} onApprove={onApprove} />);

    fireEvent.click(screen.getByRole("button", { name: "승인하기" }));

    expect(onApprove).toHaveBeenCalledTimes(1);
  });
});
