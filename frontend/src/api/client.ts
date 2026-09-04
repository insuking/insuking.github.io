import type { ReadinessResponse } from "../types/health";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function fetchReadiness(): Promise<ReadinessResponse> {
  const response = await fetch(`${API_BASE_URL}/health/ready`);
  if (!response.ok && response.status !== 503) {
    throw new Error(`Unexpected readiness status: ${response.status}`);
  }
  return (await response.json()) as ReadinessResponse;
}
