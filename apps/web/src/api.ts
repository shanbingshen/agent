export const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

export type User = { id: string; email: string; role: "admin" | "analyst" | "approver" };
export type Device = { id: { id: string }; name: string; type: string };
export type ControlPlan = {
  id: string; device_id: string; device_name: string; device_type: string;
  method: string; params: Record<string, unknown>; reason: string;
  risk_level: string; status: string; created_at: string; expires_at: string;
  execution_result?: Record<string, unknown>;
};

export type DailySummary = {
  id: string;
  summary_date: string;
  period_start: string;
  period_end: string;
  title: string;
  content: string;
  device_scope: string[];
  statistics: {
    overview?: {
      device_count: number;
      available_device_count: number;
      warning_count: number;
      alarm_count: number;
      average_active_power_kw: number | null;
      energy_consumption_kwh: number | null;
    };
  };
  warnings: Array<{ severity?: string; device_name?: string; message?: string }>;
  model_name: string;
  status: string;
  trigger: string;
  created_at: string;
};

export async function api<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || "请求失败");
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
