/**
 * Account balance / safety-check / emergency-stop API types (P45) -
 * mirror backend/app/api/dashboard.py's response models.
 */

export interface Balance {
  kis_total_value: number | null;
  upbit_total_value: number | null;
  total_assets: number;
}

export interface BalanceSnapshot {
  as_of: string;
  total_assets: number;
}

export interface BalanceHistory {
  window: string;
  snapshots: BalanceSnapshot[];
}

export type SafetyCheckStatus = "ok" | "warning" | "manual_check";

export interface SafetyCheckItem {
  key: string;
  label: string;
  status: SafetyCheckStatus;
  detail: string;
}

export interface SafetyCheck {
  items: SafetyCheckItem[];
  all_ok: boolean;
}

export interface EmergencyStopResult {
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
}
