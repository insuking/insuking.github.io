import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { StockRadarLatest } from "../types/stockRadar";
import { StockRadarPage } from "./StockRadarPage";

function buildLatest(overrides: Partial<StockRadarLatest> = {}): StockRadarLatest {
  return {
    scan_run_id: "run-1",
    scored_at: new Date().toISOString(),
    candidates: [],
    ...overrides,
  };
}

describe("StockRadarPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an honest empty state when no scan has run yet, never sample data", async () => {
    vi.spyOn(client, "fetchStockRadarLatest").mockResolvedValue(buildLatest());

    render(<StockRadarPage />);

    await waitFor(() =>
      expect(
        screen.getByText("아직 스캔 결과가 없습니다. scripts/scan_stocks.py를 먼저 실행하세요."),
      ).toBeInTheDocument(),
    );
  });

  it("renders one card per real candidate", async () => {
    vi.spyOn(client, "fetchStockRadarLatest").mockResolvedValue(
      buildLatest({
        candidates: [
          {
            symbol: "005930",
            name: "삼성전자",
            rank: 1,
            total_score: 43.9,
            max_available: 77,
            positive: [],
            negative: [],
          },
          {
            symbol: "000660",
            name: "SK하이닉스",
            rank: 2,
            total_score: 46.8,
            max_available: 77,
            positive: [],
            negative: [],
          },
        ],
      }),
    );

    render(<StockRadarPage />);

    await waitFor(() => expect(screen.getAllByTestId("stock-radar-card")).toHaveLength(2));
    expect(screen.getByText("005930 (삼성전자)")).toBeInTheDocument();
    expect(screen.getByText("000660 (SK하이닉스)")).toBeInTheDocument();
  });

  it("shows a load error when the fetch fails", async () => {
    vi.spyOn(client, "fetchStockRadarLatest").mockRejectedValue(new Error("network down"));

    render(<StockRadarPage />);

    await waitFor(() => expect(screen.getByText("데이터를 불러오지 못했습니다.")).toBeInTheDocument());
  });
});
