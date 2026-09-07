/**
 * Dashboard HTTP API types (P21) - mirror backend/app/api/dashboard.py's
 * response models. `positions`/`top_opportunities`/`risk_used`/
 * `service_health` reuse the P1 domain shapes (see types/domain.ts)
 * because the backend endpoint returns those models directly rather than
 * a bespoke DTO - everything else here is purpose-built for this API.
 */

import type { Position, Recommendation, RiskState, SystemHealth } from "./domain";

export interface DashboardSummary {
  market_regime: string | null;
  btc_regime: string | null;
  overall_health: string;
  service_health: SystemHealth[];
  open_incidents: number;
  pending_approvals: number;
  top_opportunities: Recommendation[];
  positions: Position[];
  risk_used: RiskState | null;
}

export interface IncidentOut {
  id: string;
  service: string;
  severity: string;
  failure_type: string;
  detected_at: string;
  safe_action: string | null;
  recovery_attempts: number;
  recovered_at: string | null;
  verification_result: string | null;
  human_action_required: boolean;
}

export interface PerformanceSummary {
  realized_pnl: number;
  win_count: number;
  loss_count: number;
  trade_count: number;
}

export interface DashboardPerformance {
  real: PerformanceSummary;
  paper: PerformanceSummary;
}
