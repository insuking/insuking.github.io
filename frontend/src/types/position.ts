/**
 * Position detail / manual controls API types (P46) - mirror
 * backend/app/api/positions.py's response models.
 */

export interface ProtectiveOrderOut {
  kind: string;
  trigger_price: number;
  quantity: number;
  active: boolean;
}

export interface PositionDetail {
  id: string;
  symbol: string;
  asset_type: string;
  state: string;
  quantity: number;
  avg_entry_price: number;
  stop_price: number;
  guardian_active: boolean;
  opened_at: string;
  updated_at: string;
  current_price: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  protective_orders: ProtectiveOrderOut[];
}

export interface GuardianToggleResult {
  id: string;
  guardian_active: boolean;
}

export interface ManualCloseResult {
  id: string;
  state: string;
  order_id: string;
  order_status: string;
}

export interface RiskStateSnapshot {
  as_of: string;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  daily_loss: number;
  daily_loss_limit: number;
  exposure: number;
  exposure_limit: number;
}

export interface RiskStateHistory {
  snapshots: RiskStateSnapshot[];
}
