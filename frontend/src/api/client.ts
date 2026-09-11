import type { CallbackResponse, LoginUrlResponse } from "../types/auth";
import type {
  ApprovalDecisionType,
  ApprovalDetail,
  DecideResult,
  PendingApprovalsResponse,
} from "../types/approval";
import type {
  DashboardPerformance,
  DashboardSummary,
  IncidentOut,
  PositionPricesResponse,
} from "../types/dashboard";
import type { ReadinessResponse } from "../types/health";
import type { StockRadarLatest } from "../types/stockRadar";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function fetchReadiness(): Promise<ReadinessResponse> {
  const response = await fetch(`${API_BASE_URL}/health/ready`);
  if (!response.ok && response.status !== 503) {
    throw new Error(`Unexpected readiness status: ${response.status}`);
  }
  return (await response.json()) as ReadinessResponse;
}

export class ApprovalApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApprovalApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function _readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function fetchApproval(token: string, userId: string): Promise<ApprovalDetail> {
  const response = await fetch(`${API_BASE_URL}/api/approvals/${token}`, {
    headers: { "X-User-Id": userId },
  });
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as ApprovalDetail;
}

export interface DecideApprovalBody {
  decision: ApprovalDecisionType;
  override_amount?: number;
  pin?: string;
}

export async function decideApproval(
  token: string,
  userId: string,
  body: DecideApprovalBody,
): Promise<DecideResult> {
  const response = await fetch(`${API_BASE_URL}/api/approvals/${token}/decide`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Id": userId },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as DecideResult;
}

export async function fetchPendingApprovals(userId: string): Promise<PendingApprovalsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/approvals`, {
    headers: { "X-User-Id": userId },
  });
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as PendingApprovalsResponse;
}

export async function fetchPositionsLivePrices(): Promise<PositionPricesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/dashboard/positions/live-prices`);
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as PositionPricesResponse;
}

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const response = await fetch(`${API_BASE_URL}/api/dashboard/summary`);
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as DashboardSummary;
}

export async function fetchIncidents(): Promise<IncidentOut[]> {
  const response = await fetch(`${API_BASE_URL}/api/dashboard/incidents`);
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as IncidentOut[];
}

export async function fetchPerformance(): Promise<DashboardPerformance> {
  const response = await fetch(`${API_BASE_URL}/api/dashboard/performance`);
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as DashboardPerformance;
}

export async function fetchStockRadarLatest(): Promise<StockRadarLatest> {
  const response = await fetch(`${API_BASE_URL}/api/stock-radar/latest`);
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as StockRadarLatest;
}

export async function fetchKakaoLoginUrl(): Promise<LoginUrlResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/kakao/login-url`);
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as LoginUrlResponse;
}

export async function submitKakaoCallback(code: string, state: string): Promise<CallbackResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/kakao/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, state }),
  });
  if (!response.ok) {
    throw new ApprovalApiError(response.status, await _readDetail(response));
  }
  return (await response.json()) as CallbackResponse;
}
