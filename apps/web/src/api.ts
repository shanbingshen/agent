export const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:18089/api/v1";

export type WorkspaceContext = "overview" | "demand" | "quality" | "compressor" | "carbon" | "events";
export type ContextTimeScope = "realtime" | "today" | "yesterday" | "last_24h" | "last_7d" | "current_month";
export type User = { id: string; tenant_id: string; email: string; role: "admin" | "analyst" | "approver" };
export type Factory = { id: string; tenant_id: string; code: string; name: string; is_active: boolean };
export type Device = { id: { id: string }; name: string; type: string };
export type ControlPlan = {
  id: string; device_id: string; device_name: string; device_type: string;
  method: string; params: Record<string, unknown>; reason: string;
  risk_level: string; status: string; created_at: string; expires_at: string;
  execution_result?: Record<string, unknown>;
};

export type DailySummary = {
  id: string;
  tenant_id: string;
  factory_id: string;
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

export type ChatRequest = {
  request_id?: string;
  thread_id: string;
  message: string;
  device_scope: string[];
  page_context?: { factory_id?: string; selected_device_ids: string[]; workspace?: WorkspaceContext; time_scope?: ContextTimeScope };
  debug?: boolean;
};

export type ChatEventContent = Record<string, unknown>;
export type ChatStreamEvent = {
  event: "node" | "tool" | "message" | "error" | "done";
  node?: string;
  content?: ChatEventContent;
};

export type CustomerAnswerMeta = {
  result_kind: "fact" | "historical_statistic" | "prediction" | "inference" | "recommendation" | "mixed" | "data_insufficient";
  capability_state: "configured" | "not_configured" | "data_insufficient" | "model_unavailable" | "reference_only";
  data_snapshot_at: string;
  data_cutoff_at?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  period_label: string;
  updating: boolean;
  metric_basis: string;
  device_names: string[];
  workspace?: WorkspaceContext | null;
  data_quality: "高" | "中" | "低" | "未知";
  expert_supplement_status: "provided" | "empty" | "unavailable" | "not_configured" | "not_applicable";
  evidence: Array<{ label: string; value: string }>;
};

export type ChatFeedbackReason = "inaccurate_data" | "not_answered" | "missing_evidence" | "wrong_context" | "unclear_expression" | "other";
export type ChatFeedbackRequest = {
  request_id: string;
  thread_id: string;
  message_id: string;
  rating: "helpful" | "needs_improvement";
  reasons: ChatFeedbackReason[];
  comment: string;
};

export type TelemetrySample = {
  ts: number;
  value: string | number | boolean;
};
export type TelemetryPayload = Record<string, TelemetrySample[]>;

export type PowerAnalysisResult = {
  data_status: string;
  warnings?: Array<{ severity?: string; message?: string; device_name?: string }>;
  metrics?: {
    demand?: Record<string, {
      average_load_kw?: number | null;
      max_demand_15m_kw?: number | null;
      instantaneous_peak_kw?: number | null;
      peak_average_ratio?: number | null;
      declared_demand_kw?: number | null;
    }>;
    quality?: Record<string, {
      power_factor?: { latest?: number; min?: number; max?: number } | null;
      current_unbalance?: { latest?: number; max?: number } | null;
      thdu?: Record<string, { latest?: number; max?: number }>;
      thdi?: Record<string, { latest?: number; max?: number }>;
    }>;
  };
};

export type LoadForecastPoint = {
  label: string;
  actual_mw: number | null;
  ai_prediction_mw: number;
  baseline_mw: number;
  limit_mw: number;
};

export type LoadForecastMockResponse = {
  unit: "MW";
  source: "mock";
  model_name: string;
  confidence: number;
  peak_prediction_mw: number;
  risk_window: string;
  points: LoadForecastPoint[];
};

export type CompressorAnalysisResult = {
  data_status: string;
  warnings?: Array<{ severity?: string; message?: string; device_name?: string }>;
  metrics?: {
    devices?: Record<string, {
      device_name?: string;
      load_rate_pct?: number | null;
      unload_rate_pct?: number | null;
      idle_running_minutes?: number | null;
      longest_idle_running_minutes?: number | null;
      idle_event_count?: number | null;
      idle_periods?: Array<{ start_ts: number; end_ts: number; duration_minutes: number }>;
      starts_per_hour?: number | null;
    }>;
    realtime?: Record<string, {
      device_name?: string;
      running?: boolean | null;
      loaded?: boolean | null;
      supply_pressure_mpa?: number | null;
      discharge_temperature_c?: number | null;
    }>;
    pressure?: Record<string, { avg_mpa?: number; min_mpa?: number; max_mpa?: number; p95_p5_mpa?: number }>;
    specific_power?: { average_kw_per_m3_min?: number | null; p95_kw_per_m3_min?: number | null } | null;
    savings_screening?: { screening_savings_kwh?: number; unloaded_energy_kwh?: number } | null;
  };
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

export async function streamChat(
  token: string,
  payload: ChatRequest,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || "AI 助手请求失败");
  }
  if (!response.body) throw new Error("AI 助手未返回流式内容");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const eventLine = block.split("\n").find(line => line.startsWith("event: "));
      const dataLine = block.split("\n").find(line => line.startsWith("data: "));
      if (!eventLine || !dataLine) continue;
      const event = JSON.parse(dataLine.slice(6)) as ChatStreamEvent;
      event.event = eventLine.slice(7) as ChatStreamEvent["event"];
      onEvent(event);
    }
  }
}

export async function sendChatFeedback(token: string, payload: ChatFeedbackRequest): Promise<void> {
  await api("/chat/feedback", token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
