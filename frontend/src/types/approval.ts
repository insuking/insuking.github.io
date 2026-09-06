/**
 * Approval HTTP API types (P13) - mirror backend/app/api/approvals.py's
 * response/request models. Purpose-built API shapes, not a 1:1 mirror of
 * the P1 `Approval` domain model (see that module's docstring for why).
 */

export type ApprovalDecisionType = "APPROVE" | "APPROVE_WITH_AMOUNT_CHANGE" | "HOLD" | "REJECT";

export interface ApprovalDetail {
  approval_state: string;
  remaining_seconds: number;
  symbol: string;
  asset_type: string;
  entry_low: number;
  entry_high: number;
  stop_price: number;
  t1_price: number;
  t1_percent: number;
  t2_price: number;
  t2_percent: number;
  runner_percent: number;
  expected_max_loss: number;
  risk_reward: number;
  score: number;
  confidence: string;
  reasons: string[];
  risks: string[];
}

export interface DecideResult {
  approval_state: string;
}
