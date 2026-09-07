import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { DashboardSummary, IncidentOut } from "../types/dashboard";
import { SystemPage } from "./SystemPage";

function buildSummary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    market_regime: null,
    btc_regime: null,
    overall_health: "HEALTHY",
    service_health: [{ service: "database", state: "HEALTHY", detected_at: "", message: null }],
    open_incidents: 0,
    pending_approvals: 0,
    top_opportunities: [],
    positions: [],
    risk_used: null,
    ...overrides,
  };
}

function buildIncident(overrides: Partial<IncidentOut> = {}): IncidentOut {
  return {
    id: "inc-1",
    service: "database",
    severity: "LOW",
    failure_type: "DB_CONNECTION_RESET",
    detected_at: new Date().toISOString(),
    safe_action: null,
    recovery_attempts: 1,
    recovered_at: null,
    verification_result: null,
    human_action_required: false,
    ...overrides,
  };
}

describe("SystemPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("labels a recovered incident as 복구됨", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchIncidents").mockResolvedValue([
      buildIncident({ recovered_at: new Date().toISOString() }),
    ]);

    render(<SystemPage />);

    await waitFor(() => expect(screen.getByText("복구됨")).toBeInTheDocument());
  });

  it("labels an unresolved never-auto-resolved incident as 확인 필요", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchIncidents").mockResolvedValue([
      buildIncident({ human_action_required: true, failure_type: "POSITION_MISMATCH" }),
    ]);

    render(<SystemPage />);

    await waitFor(() => expect(screen.getByText("확인 필요")).toBeInTheDocument());
  });

  it("labels an unresolved auto-recoverable incident as still recovering", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(buildSummary());
    vi.spyOn(client, "fetchIncidents").mockResolvedValue([buildIncident({ human_action_required: false })]);

    render(<SystemPage />);

    await waitFor(() => expect(screen.getByText("자동복구 시도중")).toBeInTheDocument());
  });

  it("shows per-service health, not just one overall dot", async () => {
    vi.spyOn(client, "fetchDashboardSummary").mockResolvedValue(
      buildSummary({
        service_health: [
          { service: "database", state: "HEALTHY", detected_at: "", message: null },
          { service: "position_guardian", state: "OFFLINE", detected_at: "", message: null },
        ],
      }),
    );
    vi.spyOn(client, "fetchIncidents").mockResolvedValue([]);

    render(<SystemPage />);

    await waitFor(() => expect(screen.getByText("database")).toBeInTheDocument());
    expect(screen.getByText("position_guardian")).toBeInTheDocument();
    expect(screen.getByText("오프라인")).toBeInTheDocument();
  });
});
