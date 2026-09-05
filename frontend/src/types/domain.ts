/**
 * Common domain model (P1) - TypeScript mirror of backend/app/models/domain.py.
 *
 * Keep field names and shapes in sync with the backend models; the
 * `/internal/domain-schema` endpoint is the source of truth to check against.
 */

export type AssetType = "STOCK" | "CRYPTO";

export type Exchange = "KRX" | "UPBIT";

export type Market = "KOSPI" | "KOSDAQ" | "UPBIT_KRW";

export type OrderSide = "BUY" | "SELL";

export type OrderType = "MARKET" | "LIMIT";

export type OrderStatus =
  | "PENDING"
  | "SUBMITTED"
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "CANCELLED"
  | "REJECTED"
  | "EXPIRED"
  | "UNKNOWN";

export type PositionState = "OPEN" | "T1_FILLED" | "T2_FILLED" | "RUNNER" | "CLOSED";

/** See docs/MASTER_SPEC.md section E. */
export type ApprovalState =
  | "CREATED"
  | "NOTIFIED"
  | "OPENED"
  | "APPROVED"
  | "REJECTED"
  | "EXPIRED"
  | "INVALIDATED"
  | "EXECUTED"
  | "BLOCKED_BY_RISK";

/** See docs/MASTER_SPEC.md section Q. */
export type HealthState = "HEALTHY" | "DEGRADED" | "RECOVERING" | "PAUSED" | "CRITICAL" | "OFFLINE";

export interface Quote {
  symbol: string;
  asset_type: AssetType;
  exchange: Exchange;
  market: Market;
  price: number;
  bid: number | null;
  ask: number | null;
  volume: number;
  exchange_ts: string;
  received_ts: string;
}

export interface Trade {
  symbol: string;
  asset_type: AssetType;
  price: number;
  quantity: number;
  side: OrderSide;
  exchange_ts: string;
  received_ts: string;
}

export interface OrderBookLevel {
  price: number;
  quantity: number;
}

export interface OrderBook {
  symbol: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  exchange_ts: string;
  received_ts: string;
}

export interface Candle {
  symbol: string;
  interval: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  open_time: string;
  close_time: string;
}

export interface Signal {
  symbol: string;
  name: string;
  value: number;
  state: string | null;
  computed_at: string;
}

export interface Recommendation {
  id: string;
  symbol: string;
  asset_type: AssetType;
  score: number;
  state: string;
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
  reasons: string[];
  risks: string[];
  created_at: string;
  expires_at: string;
}

export interface Approval {
  id: string;
  recommendation_id: string;
  user_id: string;
  state: ApprovalState;
  token_hash: string;
  created_at: string;
  notified_at: string | null;
  opened_at: string | null;
  decided_at: string | null;
  expires_at: string;
}

export interface TradePlan {
  id: string;
  approval_id: string;
  symbol: string;
  initial_qty: number;
  t1_percent: number;
  t2_percent: number;
  runner_percent: number;
  entry_price: number;
  stop_price: number;
  t1_price: number;
  t2_price: number;
}

export interface Order {
  id: string;
  trade_plan_id: string | null;
  symbol: string;
  side: OrderSide;
  order_type: OrderType;
  quantity: number;
  price: number | null;
  status: OrderStatus;
  broker: string;
  broker_order_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Fill {
  id: string;
  order_id: string;
  quantity: number;
  price: number;
  filled_at: string;
}

export interface Position {
  id: string;
  symbol: string;
  asset_type: AssetType;
  quantity: number;
  avg_entry_price: number;
  stop_price: number;
  state: PositionState;
  guardian_active: boolean;
  opened_at: string;
  updated_at: string;
}

export interface RiskState {
  as_of: string;
  daily_loss: number;
  daily_loss_limit: number;
  exposure: number;
  exposure_limit: number;
  open_positions: number;
  max_positions: number;
  consecutive_stops: number;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
}

export interface SystemHealth {
  service: string;
  state: HealthState;
  detected_at: string;
  message: string | null;
}
