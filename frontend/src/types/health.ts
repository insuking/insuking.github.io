export type HealthCheckStatus = "ok" | "fail";

export interface ReadinessResponse {
  status: "ready" | "not_ready";
  checks: {
    database: HealthCheckStatus;
    redis: HealthCheckStatus;
  };
}
