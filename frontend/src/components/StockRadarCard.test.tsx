import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StockRadarCandidate } from "../types/stockRadar";
import { StockRadarCard } from "./StockRadarCard";

function buildCandidate(overrides: Partial<StockRadarCandidate> = {}): StockRadarCandidate {
  return {
    symbol: "005930",
    name: "삼성전자",
    rank: 1,
    total_score: 43.9,
    max_available: 77,
    positive: [{ factor: "box_compression", points: 10, detail: "변동폭이 최근 구간 중 상위 100%로 압축" }],
    negative: [],
    ...overrides,
  };
}

describe("StockRadarCard", () => {
  it("renders rank, symbol, name, and the score over its own denominator", () => {
    render(<StockRadarCard candidate={buildCandidate()} />);

    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("005930 (삼성전자)")).toBeInTheDocument();
    expect(screen.getByText("44 / 77")).toBeInTheDocument();
  });

  it("falls back to the bare symbol when no name is available", () => {
    render(<StockRadarCard candidate={buildCandidate({ name: null })} />);

    expect(screen.getByText("005930")).toBeInTheDocument();
  });

  it("renders positive and negative factor details", () => {
    render(
      <StockRadarCard
        candidate={buildCandidate({
          negative: [{ factor: "obv_falling", points: 0, detail: "OBV(누적거래량)가 하락 중" }],
        })}
      />,
    );

    expect(screen.getByText("변동폭이 최근 구간 중 상위 100%로 압축")).toBeInTheDocument();
    expect(screen.getByText("OBV(누적거래량)가 하락 중")).toBeInTheDocument();
  });
});
