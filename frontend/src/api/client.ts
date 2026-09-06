import type { ApprovalDecisionType, ApprovalDetail, DecideResult } from "../types/approval";
import type { ReadinessResponse } from "../types/health";

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
