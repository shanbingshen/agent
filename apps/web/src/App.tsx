import { FormEvent, KeyboardEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type ChatFeedbackReason,
  type ChatStreamEvent,
  type CompressorAnalysisResult,
  type ContextTimeScope,
  type CustomerAnswerMeta,
  type DailySummary,
  type DemandForecastResponse,
  type Device,
  type Factory,
  type PowerAnalysisResult,
  sendChatFeedback,
  streamChat,
  type TelemetryPayload,
  type User,
  type WorkspaceContext,
} from "./api";

type Workspace = WorkspaceContext;
type Alarm = { type: string; severity: string; status: string; created_time: number };
type DeviceSnapshot = {
  device: Device;
  telemetry: TelemetryPayload;
  history: TelemetryPayload;
  insightHistory: TelemetryPayload;
  monthHistory: TelemetryPayload;
  alarms: Alarm[];
};
type AssistantMessage = {
  id: string;
  who: "ai" | "you";
  text: string;
  createdAt?: string;
  requestId?: string;
  meta?: CustomerAnswerMeta;
  tools?: string[];
  errorCode?: string;
  stopped?: boolean;
};
type InsightTone = "cyan" | "amber" | "green" | "muted";
type InsightMetric = { label: string; value: string; tone?: InsightTone };
type InsightEvidence = { label: string; value: string };
type PageInsight = {
  id: string;
  icon: string;
  tone: InsightTone;
  title: string;
  summary: string;
  badge: string;
  detailTitle: string;
  detailSummary: string;
  metrics: InsightMetric[];
  evidence: InsightEvidence[];
  prompt: string;
  daily?: {
    headline?: { label: string; value: string; unit?: string; change?: string; changeTone?: "green" | "amber" };
    chart?: ChartData;
    note?: string;
    footer?: { label: string; value: string; unit?: string; confidence?: string };
    items?: Array<{ label: string; value?: string; tone?: "green" | "amber" }>;
  };
};
type ChartSeries = {
  name: string;
  values: Array<number | null | undefined>;
  color: string;
  dashed?: boolean;
  width?: number;
};
type ChartData = {
  labels: string[];
  unit: string;
  series: ChartSeries[];
};

const ASSISTANT_THREAD_KEY = "arthra_assistant_thread_id";
const ASSISTANT_MESSAGES_KEY = "arthra_assistant_messages";

const timeScopeLabels: Record<ContextTimeScope, string> = {
  realtime: "当前最新",
  today: "今日自然日",
  yesterday: "昨日自然日",
  last_24h: "最近24小时",
  last_7d: "最近7天",
  current_month: "本月",
};

const resultKindLabels: Record<CustomerAnswerMeta["result_kind"], string> = {
  fact: "当前事实",
  historical_statistic: "历史统计",
  prediction: "预测结果",
  inference: "辅助推断",
  recommendation: "建议",
  mixed: "综合分析",
  data_insufficient: "数据不足",
};

const capabilityStateLabels: Record<CustomerAnswerMeta["capability_state"], string> = {
  configured: "能力已配置",
  not_configured: "能力未配置",
  data_insufficient: "数据不足",
  model_unavailable: "模型不可用",
  reference_only: "知识说明",
};

const feedbackReasonLabels: Record<ChatFeedbackReason, string> = {
  inaccurate_data: "数据不准确",
  not_answered: "没有回答问题",
  missing_evidence: "缺少证据",
  wrong_context: "设备或时间错误",
  unclear_expression: "表达不清",
  other: "其他",
};

function clearAssistantSession() {
  sessionStorage.removeItem(ASSISTANT_THREAD_KEY);
  sessionStorage.removeItem(ASSISTANT_MESSAGES_KEY);
}

function loadAssistantThreadId(): string {
  const current = sessionStorage.getItem(ASSISTANT_THREAD_KEY);
  if (current) return current;
  const created = `assistant-${crypto.randomUUID()}`;
  sessionStorage.setItem(ASSISTANT_THREAD_KEY, created);
  return created;
}

function loadAssistantMessages(): AssistantMessage[] {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(ASSISTANT_MESSAGES_KEY) || "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is AssistantMessage => {
      if (!item || typeof item !== "object") return false;
      const message = item as Partial<AssistantMessage>;
      return typeof message.id === "string"
        && (message.who === "ai" || message.who === "you")
        && typeof message.text === "string";
    }).slice(-40);
  } catch {
    return [];
  }
}

const navItems: Array<{ id: Workspace; label: string; icon: string }> = [
  { id: "overview", label: "首页", icon: "⌂" },
  { id: "demand", label: "需量管理", icon: "▣" },
  { id: "quality", label: "电能质量", icon: "∿" },
  { id: "compressor", label: "空压系统", icon: "▦" },
  { id: "carbon", label: "碳减排", icon: "◒" },
  { id: "events", label: "智能事件", icon: "◎" },
];

const toolLabels: Record<string, string> = {
  get_meter_realtime: "实时功率",
  get_energy_consumption: "周期电量",
  compare_energy_periods: "电量对比",
  calculate_rolling_15m_max_demand: "15分钟最大需量",
  detect_power_peaks: "负荷峰值",
  analyze_peak_average_ratio: "峰均比",
  detect_declared_demand_exceedance: "需量控制目标越限",
  detect_voltage_deviation: "电压偏差",
  detect_three_phase_imbalance: "三相不平衡",
  detect_power_factor_anomaly: "功率因数",
  detect_thdu_thdi_anomaly: "THD异常",
  analyze_3_5_7_harmonics: "谐波特征",
  calculate_power_quality_abnormal_duration: "异常持续时间",
  get_compressor_realtime: "空压实时状态",
  analyze_compressor_load_unload_rate: "加载/卸载率",
  detect_compressor_idle_running: "空载运行",
  detect_compressor_frequent_starts: "频繁启停",
  analyze_compressor_pressure_fluctuation: "压力波动",
  detect_compressor_high_supply_pressure: "供气压力",
  calculate_compressor_specific_power: "系统比功率",
  detect_compressor_leakage: "泄漏筛查",
  estimate_compressor_energy_saving: "节能量筛查",
};

function valueOf(payload: TelemetryPayload | undefined, key: string): number | undefined {
  const samples = payload?.[key];
  if (!samples?.length) return undefined;
  const latest = samples.reduce((current, sample) => sample.ts > current.ts ? sample : current);
  if (typeof latest.value === "number" && Number.isFinite(latest.value)) return latest.value;
  if (typeof latest.value === "string" && latest.value.trim() !== "") {
    const parsed = Number(latest.value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function stateOf(payload: TelemetryPayload | undefined, key: string): string | undefined {
  const samples = payload?.[key];
  if (!samples?.length) return undefined;
  const latest = samples.reduce((current, sample) => sample.ts > current.ts ? sample : current);
  return String(latest.value);
}

function samplesOf(payload: TelemetryPayload | undefined, key: string): Array<{ ts: number; value: number }> {
  return (payload?.[key] || [])
    .map(sample => ({ ts: sample.ts, value: typeof sample.value === "number" ? sample.value : Number(sample.value) }))
    .filter(sample => Number.isFinite(sample.value))
    .sort((a, b) => a.ts - b.ts);
}

function counterCurve(
  payload: TelemetryPayload | undefined,
  key: string,
  startTs: number,
  endTs: number,
): Array<{ ts: number; value: number }> {
  const samples = samplesOf(payload, key).filter(sample => sample.ts >= startTs && sample.ts <= endTs);
  if (samples.length < 2) return [];
  const baseline = samples[0].value;
  return samples
    .map(sample => ({ ts: sample.ts, value: Math.max(0, sample.value - baseline) }))
    .filter((sample, index, rows) => index === 0 || sample.value >= rows[index - 1].value);
}

type DemandProjection = {
  labels: string[];
  actual: Array<number | null>;
  forecast: Array<number | null>;
  lower: Array<number | null>;
  upper: Array<number | null>;
  currentDemandKw?: number;
  predictedMaxKw?: number;
  currentSlot: number;
  peakTime?: string;
  methodLabel: string;
  dataBasis: string;
  qualityGrade: "高" | "中高" | "中" | "低" | "计算中";
  validationMaeKw?: number;
};

function buildDemandProjection(payload: TelemetryPayload | undefined): DemandProjection {
  const now = new Date();
  const todayStart = new Date(now);
  todayStart.setHours(0, 0, 0, 0);
  const yesterdayStart = new Date(todayStart);
  yesterdayStart.setDate(yesterdayStart.getDate() - 1);
  const todayStartTs = todayStart.getTime();
  const yesterdayStartTs = yesterdayStart.getTime();
  const nowTs = now.getTime();
  const samples = samplesOf(payload, "meter_TotW");
  const buckets = new Map<number, { total: number; count: number }>();
  for (const sample of samples) {
    const date = new Date(sample.ts);
    const dayOffset = sample.ts >= todayStartTs && sample.ts <= nowTs
      ? 96
      : sample.ts >= yesterdayStartTs && sample.ts < todayStartTs
        ? 0
        : -96;
    if (dayOffset < 0) continue;
    const slot = dayOffset + date.getHours() * 4 + Math.floor(date.getMinutes() / 15);
    const current = buckets.get(slot) || { total: 0, count: 0 };
    current.total += sample.value;
    current.count += 1;
    buckets.set(slot, current);
  }
  const valueAt = (slot: number) => {
    const bucket = buckets.get(slot);
    return bucket ? bucket.total / bucket.count : undefined;
  };
  const labels = Array.from({ length: 96 }, (_, slot) => {
    const hours = Math.floor(slot / 4).toString().padStart(2, "0");
    const minutes = (slot % 4 * 15).toString().padStart(2, "0");
    return `${hours}:${minutes}`;
  });
  const wallClockSlot = Math.min(95, now.getHours() * 4 + Math.floor(now.getMinutes() / 15));
  const actual = labels.map((_, slot) => slot <= wallClockSlot ? valueAt(96 + slot) ?? null : null);
  const latestActualSlot = actual.reduce<number>(
    (latest, value, index) => typeof value === "number" ? index : latest,
    -1,
  );
  const currentSlot = latestActualSlot >= 0 ? latestActualSlot : wallClockSlot;
  const currentDemandKw = [...actual].reverse().find((value): value is number => typeof value === "number") ?? undefined;
  const yesterdayComparable = valueAt(currentSlot);
  const correction = currentDemandKw != null && yesterdayComparable
    ? Math.max(0.75, Math.min(1.25, currentDemandKw / yesterdayComparable))
    : 1;
  const forecast = labels.map((_, slot) => {
    if (slot < currentSlot) return null;
    if (slot === currentSlot && currentDemandKw != null) return currentDemandKw;
    const yesterdayValue = valueAt(slot);
    if (yesterdayValue != null) return yesterdayValue * correction;
    return currentDemandKw ?? null;
  });
  const predictedValues = forecast.filter((value): value is number => typeof value === "number");
  const matchedFutureSlots = labels.slice(currentSlot + 1).filter((_, index) => valueAt(currentSlot + 1 + index) != null).length;
  const futureSlots = Math.max(1, 95 - currentSlot);
  return {
    labels,
    actual,
    forecast,
    lower: labels.map(() => null),
    upper: labels.map(() => null),
    currentDemandKw,
    predictedMaxKw: predictedValues.length ? Math.max(...predictedValues) : undefined,
    currentSlot,
    methodLabel: "短时基线预测",
    dataBasis: "昨日曲线校正",
    qualityGrade: matchedFutureSlots / futureSlots >= 0.8 ? "中" : "计算中",
  };
}

function machineDemandProjection(forecast: DemandForecastResponse): DemandProjection {
  return {
    labels: forecast.points.map(point => point.label),
    actual: forecast.points.map(point => point.actual_kw),
    forecast: forecast.points.map(point => point.prediction_kw),
    lower: forecast.points.map(point => point.lower_kw),
    upper: forecast.points.map(point => point.upper_kw),
    currentDemandKw: forecast.current_demand_kw,
    predictedMaxKw: forecast.peak_prediction_kw,
    currentSlot: forecast.current_slot,
    peakTime: forecast.peak_time,
    methodLabel: forecast.method_label,
    dataBasis: forecast.data_basis,
    qualityGrade: forecast.quality_grade,
    validationMaeKw: forecast.validation_mae_kw,
  };
}

function format(value: number | undefined | null, digits = 1): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
}

function latestRecord<T>(values: Record<string, T> | undefined): T | undefined {
  return values ? Object.values(values)[0] : undefined;
}

function inlineMarkdown(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part,
  );
}

function Markdown({ text }: { text: string }) {
  return <div className="markdown">{text.split(/\r?\n/).map((raw, index) => {
    const line = raw.trim();
    if (!line) return <div className="markdown-space" key={index} />;
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) return <h4 key={index}>{inlineMarkdown(heading[2])}</h4>;
    if (line.startsWith("- ")) return <div className="markdown-item" key={index}><i />{inlineMarkdown(line.slice(2))}</div>;
    const ordered = line.match(/^(\d+)\.\s+(.+)$/);
    if (ordered) return <div className="markdown-item" key={index}><b>{ordered[1]}</b>{inlineMarkdown(ordered[2])}</div>;
    if (line.startsWith("> ")) return <blockquote key={index}>{inlineMarkdown(line.slice(2))}</blockquote>;
    return <p key={index}>{inlineMarkdown(line)}</p>;
  })}</div>;
}

function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [email, setEmail] = useState("admin@arthra.local");
  const [password, setPassword] = useState("Arthra@123456");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || "http://localhost:18089/api/v1"}/auth/login`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }),
      });
      if (!response.ok) throw new Error("登录失败，请检查账号和密码");
      onLogin((await response.json()).access_token);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally { setBusy(false); }
  }
  return <main className="login-shell">
    <div className="login-brand"><strong>AethraVista<sup>TM</sup></strong><span>AI 能碳运营管理平台</span></div>
    <form className="login-panel" onSubmit={submit}>
      <p>INDUSTRIAL INTELLIGENCE</p><h1>进入能碳驾驶舱</h1>
      <label>账号<input value={email} onChange={event => setEmail(event.target.value)} autoComplete="username" /></label>
      <label>密码<input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" /></label>
      {error && <div className="error-banner">{error}</div>}
      <button disabled={busy}>{busy ? "正在连接…" : "登录"}</button>
    </form>
  </main>;
}

function useOperationsData(token: string, factoryId: string) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [snapshots, setSnapshots] = useState<DeviceSnapshot[]>([]);
  const [summaries, setSummaries] = useState<DailySummary[]>([]);
  const [powerAnalysis, setPowerAnalysis] = useState<PowerAnalysisResult | null>(null);
  const [compressorAnalysis, setCompressorAnalysis] = useState<CompressorAnalysisResult | null>(null);
  const [demandForecast, setDemandForecast] = useState<DemandForecastResponse | null>(null);
  const [loading, setLoading] = useState(Boolean(token && factoryId));
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token || !factoryId) {
      setDevices([]); setSnapshots([]); setSummaries([]);
      setPowerAnalysis(null); setCompressorAnalysis(null);
      setDemandForecast(null);
      setLoading(false);
      return;
    }
    const factoryQuery = `factory_id=${encodeURIComponent(factoryId)}`;
    setDemandForecast(null);
    let active = true;
    async function load() {
      setLoading(true); setError("");
      try {
        const page = await api<{ data: Device[] }>(`/devices?${factoryQuery}`, token);
        const relevant = (page.data || []).filter(device => ["ems", "meter", "compressor"].includes(device.type));
        if (!active) return;
        setDevices(relevant);
        const now = Date.now();
        const start = now - 24 * 60 * 60 * 1000;
        const insightStartDate = new Date(now);
        insightStartDate.setHours(0, 0, 0, 0);
        insightStartDate.setDate(insightStartDate.getDate() - 1);
        const insightStart = insightStartDate.getTime();
        const monthStartDate = new Date(now);
        monthStartDate.setDate(1);
        monthStartDate.setHours(0, 0, 0, 0);
        const monthStart = monthStartDate.getTime();
        const rows = await Promise.all(relevant.map(async device => {
          const keys = device.type === "meter"
            ? ["meter_TotW", "meter_SupWh", "meter_TotPF", "meter_ImbNgV", "meter_ImbNgA", "meter_ThdPhV_phsA", "meter_ThdPhV_phsB", "meter_ThdPhV_phsC", "meter_ThdA_phsA", "meter_ThdA_phsB", "meter_ThdA_phsC"]
            : device.type === "compressor"
              ? ["air_comp_supply_pressure", "air_comp_discharge_temp", "air_comp_running_state", "air_comp_load_state", "air_comp_running_flag", "air_comp_loaded_flag", "air_comp_fad_flow_m3_min"]
              : ["power_kw", "energy_kwh", "soc", "mode"];
          const keyQuery = encodeURIComponent(keys.join(","));
          const [telemetry, history, insightHistory, monthHistory, alarmPage] = await Promise.all([
            api<TelemetryPayload>(`/devices/${device.id.id}/telemetry?keys=${keyQuery}&${factoryQuery}`, token).catch(() => ({})),
            api<TelemetryPayload>(`/devices/${device.id.id}/telemetry?keys=${keyQuery}&start_ts=${start}&end_ts=${now}&${factoryQuery}`, token).catch(() => ({})),
            device.type === "meter"
              ? api<TelemetryPayload>(
                `/devices/${device.id.id}/telemetry?keys=meter_TotW%2Cmeter_SupWh&start_ts=${insightStart}&end_ts=${now}&agg=AVG&interval_ms=300000&limit=1000&${factoryQuery}`,
                token,
              ).catch(() => ({}))
              : Promise.resolve({} as TelemetryPayload),
            device.type === "meter"
              ? api<TelemetryPayload>(
                `/devices/${device.id.id}/telemetry?keys=meter_SupWh&start_ts=${monthStart}&end_ts=${now}&agg=MAX&interval_ms=3600000&limit=1000&${factoryQuery}`,
                token,
              ).catch(() => ({}))
              : Promise.resolve({} as TelemetryPayload),
            api<{ data: Alarm[] }>(`/devices/${device.id.id}/alarms?${factoryQuery}`, token).catch(() => ({ data: [] })),
          ]);
          return { device, telemetry, history, insightHistory, monthHistory, alarms: alarmPage.data || [] };
        }));
        const recentSummaries = await api<DailySummary[]>(`/daily-summaries?limit=7&${factoryQuery}`, token).catch(() => []);
        if (!active) return;
        setSnapshots(rows); setSummaries(recentSummaries);

        const meter = relevant.find(device => device.type === "meter");
        const compressor = relevant.find(device => device.type === "compressor");
        if (meter) {
          void api<DemandForecastResponse>(
            `/demand-forecast?device_id=${encodeURIComponent(meter.id.id)}&${factoryQuery}`,
            token,
          ).then(result => active && setDemandForecast(result)).catch(() => active && setDemandForecast(null));
          void api<PowerAnalysisResult>(`/power-analysis?${factoryQuery}`, token, {
            method: "POST",
            body: JSON.stringify({
              message: "为前端驾驶舱计算需量与电能质量指标",
              device_scope: [meter.id.id], interval_seconds: 300,
              capabilities: ["demand_15m", "peak_average_ratio", "declared_demand_exceedance", "power_factor", "phase_imbalance", "thd", "harmonics", "abnormal_duration"],
            }),
          }).then(result => active && setPowerAnalysis(result)).catch(() => active && setPowerAnalysis(null));
        }
        if (compressor) {
          void api<CompressorAnalysisResult>(`/compressor-analysis?${factoryQuery}`, token, {
            method: "POST",
            body: JSON.stringify({
              message: "为前端驾驶舱计算空压系统运行指标",
              device_scope: [compressor.id.id], interval_seconds: 300,
              capabilities: ["realtime_status", "load_rate", "idle_running", "frequent_start", "pressure_fluctuation", "high_pressure", "specific_power", "leakage", "savings"],
            }),
          }).then(result => active && setCompressorAnalysis(result)).catch(() => active && setCompressorAnalysis(null));
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "工业数据加载失败");
      } finally { if (active) setLoading(false); }
    }
    void load();
    const timer = window.setInterval(load, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [token, factoryId]);

  async function refreshSummary() {
    if (!token || !factoryId || summaryBusy) return;
    setSummaryBusy(true);
    setError("");
    try {
      const summary = await api<DailySummary>("/daily-summaries/generate", token, {
        method: "POST",
        body: JSON.stringify({
          factory_id: factoryId,
          device_scope: devices.map(device => device.id.id),
        }),
      });
      setSummaries(current => [summary, ...current.filter(item => item.id !== summary.id)].slice(0, 7));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "AI 每日摘要生成失败");
    } finally {
      setSummaryBusy(false);
    }
  }

  return { devices, snapshots, summaries, powerAnalysis, compressorAnalysis, demandForecast, loading, error, summaryBusy, refreshSummary };
}

function chartValues(series: ChartSeries[]): number[] {
  return series.flatMap(item => item.values).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
}

function linePath(values: Array<number | null | undefined>, min: number, max: number, width = 600, height = 180): string {
  const points = values.map((value, index) => {
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    const x = values.length <= 1 ? 0 : index / (values.length - 1) * width;
    const y = 14 + (1 - (value - min) / (max - min || 1)) * (height - 28);
    return { x, y };
  });
  let d = "";
  let previous: { x: number; y: number } | null = null;
  points.forEach(point => {
    if (!point) {
      previous = null;
      return;
    }
    if (!previous) {
      d += `${d ? " " : ""}M${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    } else {
      const dx = (point.x - previous.x) / 2;
      d += ` C${(previous.x + dx).toFixed(1)} ${previous.y.toFixed(1)} ${(point.x - dx).toFixed(1)} ${point.y.toFixed(1)} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    }
    previous = point;
  });
  return d;
}

function lineAreaPath(values: Array<number | null | undefined>, min: number, max: number, width: number, height: number): string {
  const path = linePath(values, min, max, width, height);
  const validIndexes = values.flatMap((value, index) => typeof value === "number" && Number.isFinite(value) ? [index] : []);
  if (!path || !validIndexes.length) return "";
  const firstX = validIndexes[0] / Math.max(1, values.length - 1) * width;
  const lastX = validIndexes.at(-1)! / Math.max(1, values.length - 1) * width;
  return `${path} L${lastX.toFixed(1)} ${(height - 14).toFixed(1)} L${firstX.toFixed(1)} ${(height - 14).toFixed(1)} Z`;
}

function InteractiveTooltip({ data, index, x, y, alignRight = false }: { data: ChartData; index: number; x: number; y: number; alignRight?: boolean }) {
  return <div className={`chart-tooltip ${alignRight ? "right" : ""}`} style={{ left: x, top: y }}>
    <strong>{data.labels[index]}</strong>
    {data.series.map(series => <span key={series.name}><i style={{ background: series.color }} />{series.name}<b>{typeof series.values[index] === "number" ? `${format(series.values[index], 2)} ${data.unit}` : `-- ${data.unit}`}</b></span>)}
  </div>;
}

function Bars({ values, unit = "kW", labels }: { values: number[]; unit?: string; labels?: string[] }) {
  const [hover, setHover] = useState<{ index: number; x: number; y: number; right: boolean } | null>(null);
  const samples = values.length > 48
    ? values.filter((_, index) => index % Math.ceil(values.length / 48) === 0)
    : values;
  const max = Math.max(...samples, 1);
  if (!samples.length) return <div className="chart-empty">暂无24小时历史数据</div>;
  const data: ChartData = { labels: labels?.slice(0, samples.length) || samples.map((_, index) => `${index + 1}`), unit, series: [{ name: "实际", values: samples, color: "#16d7e8" }] };
  return <div className="load-bars interactive-chart" aria-label="24小时负荷趋势" onMouseLeave={() => setHover(null)}>
    {samples.map((value, index) =>
      <i key={index} style={{ height: `${Math.max(4, value / max * 100)}%` }} onMouseMove={event => {
        const root = event.currentTarget.parentElement?.getBoundingClientRect();
        const bar = event.currentTarget.getBoundingClientRect();
        if (!root) return;
        setHover({ index, x: bar.left - root.left + bar.width / 2, y: Math.max(10, bar.top - root.top - 8), right: index > samples.length * 0.65 });
      }} />
    )}
    {hover && <><span className="chart-guide" style={{ left: hover.x }} /> <InteractiveTooltip data={data} index={hover.index} x={hover.x} y={hover.y} alignRight={hover.right} /></>}
  </div>;
}

function ForecastLineChart({ forecast, limitKw }: { forecast: DemandForecastResponse | null; limitKw?: number }) {
  const [hover, setHover] = useState<{ index: number; x: number; right: boolean } | null>(null);
  if (!forecast?.points.length) return <div className="chart-empty">AI负荷预测计算中</div>;
  const actualSeries: ChartSeries = { name: "实际负荷", values: forecast.points.map(point => point.actual_kw), color: "#6488ed", width: 3 };
  const forecastSeries: ChartSeries = { name: "AI预测", values: forecast.points.map(point => point.prediction_kw), color: "#19e4c3", dashed: true, width: 2.8 };
  const limitSeries: ChartSeries = { name: "限值阈值", values: forecast.points.map(() => limitKw), color: "#91a0a5", dashed: true, width: 1.8 };
  const lower = forecast.points.map(point => point.lower_kw);
  const upper = forecast.points.map(point => point.upper_kw);
  const data: ChartData = {
    labels: forecast.points.map(point => point.label),
    unit: "kW",
    series: [actualSeries, forecastSeries, limitSeries],
  };
  const values = chartValues([
    ...data.series,
    { name: "预测下界", values: lower, color: "" },
    { name: "预测上界", values: upper, color: "" },
  ]);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const roughStep = Math.max(1, (rawMax - rawMin) / 4);
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalizedStep = roughStep / magnitude;
  const step = (normalizedStep <= 1 ? 1 : normalizedStep <= 2 ? 2 : normalizedStep <= 5 ? 5 : 10) * magnitude;
  const min = Math.max(0, Math.floor(rawMin / step) * step);
  const max = Math.max(min + step * 4, Math.ceil(rawMax / step) * step);
  const width = 900;
  const height = 260;
  const ticks = Array.from({ length: 5 }, (_, index) => max - index * (max - min) / 4);
  const pointY = (value: number) => 14 + (1 - (value - min) / (max - min || 1)) * (height - 28);
  const peakValue = forecast.peak_prediction_kw;
  const peakIndex = forecast.points.findIndex(point => Math.abs(point.prediction_kw - peakValue) < 0.001);
  const peakX = peakIndex < 0 ? 0 : peakIndex / Math.max(1, forecast.points.length - 1) * 100;
  const currentX = forecast.current_slot / Math.max(1, forecast.points.length - 1) * 100;
  const xLabels = Array.from({ length: 12 }, (_, index) => `${String(index * 2).padStart(2, "0")}:00`);
  return <div className="forecast-chart">
    <div className="overview-forecast-y-axis"><b>kW</b>{ticks.map(value => <span key={value}>{format(value, 0)}</span>)}</div>
    <div className="overview-forecast-plot interactive-chart" onMouseLeave={() => setHover(null)} onMouseMove={event => {
      const rect = event.currentTarget.getBoundingClientRect();
      const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
      const index = Math.max(0, Math.min(data.labels.length - 1, Math.round(x / rect.width * (data.labels.length - 1))));
      setHover({ index, x: data.labels.length <= 1 ? 0 : index / (data.labels.length - 1) * rect.width, right: index > data.labels.length * 0.65 });
    }}>
      <div className="overview-chart-legend">
        <span className="actual"><i />实际负荷</span>
        <span className="forecast"><i />AI预测</span>
        <span className="range"><i />预测区间</span>
        {limitKw != null && <span className="limit"><i />限值阈值</span>}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="AI负荷预测曲线">
        {ticks.map(value => <line key={value} x1="0" x2={width} y1={pointY(value)} y2={pointY(value)} className="overview-forecast-grid" />)}
        <path d={demandRangePath(lower, upper, min, max, width, height)} className="demand-range-area" />
        <path d={linePath(lower, min, max, width, height)} className="demand-range-line" />
        <path d={linePath(upper, min, max, width, height)} className="demand-range-line" />
        {limitKw != null && <path d={linePath(limitSeries.values, min, max, width, height)} className="demand-target-line" />}
        <path d={linePath(forecastSeries.values, min, max, width, height)} className="demand-ml-line" />
        <path d={linePath(actualSeries.values, min, max, width, height)} className="demand-actual-line" />
        {actualSeries.values.map((value, index) => typeof value === "number" && index % 4 === 0
          ? <circle key={index} cx={index / 95 * width} cy={pointY(value)} r="3.7" className="demand-actual-point" />
          : null)}
      </svg>
      <span className="overview-current-line" style={{ left: `${currentX}%` }}><b>当前</b></span>
      {peakIndex >= 0 && <span className="demand-peak-label overview-peak-label" style={{ left: `${peakX}%`, top: 39 + pointY(peakValue) }}>
        预计峰值 {format(peakValue, 0)} kW<i />
      </span>}
      <div className="overview-forecast-axis">{xLabels.map(label => <span key={label}>{label}</span>)}</div>
      {hover && <><span className="chart-guide" style={{ left: hover.x }} />{data.series.map(series => {
        const value = series.values[hover.index];
        if (typeof value !== "number" || !Number.isFinite(value)) return null;
        return <span key={series.name} className="chart-dot" style={{ left: hover.x, top: 39 + pointY(value), background: series.color }} />;
      })}
        <div className={`chart-tooltip overview-forecast-tooltip ${hover.right ? "right" : ""}`} style={{ left: hover.x, top: 152 }}>
          <strong>{data.labels[hover.index]}</strong>
          {typeof actualSeries.values[hover.index] === "number" && <span><i style={{ background: actualSeries.color }} />实际负荷<b>{format(actualSeries.values[hover.index], 1)} kW</b></span>}
          <span><i style={{ background: forecastSeries.color }} />AI预测<b>{format(forecastSeries.values[hover.index], 1)} kW</b></span>
          <span><i className="range-dot" />预测区间<b>{format(lower[hover.index], 1)}–{format(upper[hover.index], 1)} kW</b></span>
          {limitKw != null && <span><i style={{ background: limitSeries.color }} />限值阈值<b>{format(limitKw, 1)} kW</b></span>}
        </div>
      </>}
    </div>
  </div>;
}

function DailyLineChart({ data }: { data: ChartData }) {
  const [hover, setHover] = useState<{ index: number; x: number; right: boolean } | null>(null);
  const values = chartValues(data.series);
  if (!values.length || !data.labels.length) return <div className="chart-empty daily-chart-empty">暂无可用日内曲线</div>;
  const rawMax = Math.max(...values, 1);
  const roughStep = Math.max(1, rawMax / 4);
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalizedStep = roughStep / magnitude;
  const step = (normalizedStep <= 1 ? 1 : normalizedStep <= 2 ? 2 : normalizedStep <= 5 ? 5 : 10) * magnitude;
  const min = 0;
  const max = Math.max(step * 4, Math.ceil(rawMax / step) * step);
  const width = 600;
  const height = 128;
  const ticks = Array.from({ length: 5 }, (_, index) => max - index * max / 4);
  const xLabels = Array.from({ length: 13 }, (_, index) => String(index * 2).padStart(2, "0"));
  function pointY(value: number) {
    return 14 + (1 - (value - min) / (max - min || 1)) * (height - 28);
  }
  return <div className="daily-energy-chart">
    <div className="daily-chart-y-axis"><b>kWh</b>{ticks.map(value => <span key={value}>{format(value, 0)}</span>)}</div>
    <div className="daily-spark interactive-chart" onMouseLeave={() => setHover(null)} onMouseMove={event => {
      const rect = event.currentTarget.getBoundingClientRect();
      const relativeX = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
      const index = Math.max(0, Math.min(data.labels.length - 1, Math.round(relativeX / rect.width * (data.labels.length - 1))));
      setHover({
        index,
        x: data.labels.length <= 1 ? 0 : index / (data.labels.length - 1) * rect.width,
        right: index > data.labels.length * 0.55,
      });
    }}>
      <div className="daily-chart-legend">{data.series.map(series =>
        <span key={series.name}><i style={{ background: series.color }} />{series.name}</span>
      )}</div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="工厂日内累计能耗曲线，纵轴千瓦时，横轴每两小时">
        {ticks.map(value => <line key={value} x1="0" x2={width} y1={pointY(value)} y2={pointY(value)} className="daily-grid-line" />)}
        <path d={lineAreaPath(data.series[0].values, min, max, width, height)} className="daily-energy-area" />
        {data.series.map(series => <path
          key={series.name}
          d={linePath(series.values, min, max, width, height)}
          fill="none"
          stroke={series.color}
          strokeWidth={series.width || 2}
          strokeDasharray={series.dashed ? "7 5" : undefined}
          className="daily-energy-line"
        />)}
      </svg>
      <div className="daily-chart-x-axis">{xLabels.map(label => <span key={label}>{label}</span>)}</div>
      {hover && <><span className="chart-guide" style={{ left: hover.x }} />{data.series.map(series => {
        const value = series.values[hover.index];
        if (typeof value !== "number" || !Number.isFinite(value)) return null;
        return <span key={series.name} className="chart-dot" style={{ left: hover.x, top: 18 + pointY(value), background: series.color }} />;
      })}<InteractiveTooltip data={data} index={hover.index} x={hover.x} y={128} alignRight={hover.right} /></>}
    </div>
  </div>;
}

function demandRangePath(
  lower: Array<number | null>,
  upper: Array<number | null>,
  min: number,
  max: number,
  width: number,
  height: number,
): string {
  const point = (value: number, index: number) => {
    const x = index / Math.max(1, lower.length - 1) * width;
    const y = 14 + (1 - (value - min) / (max - min || 1)) * (height - 28);
    return `${x.toFixed(1)} ${y.toFixed(1)}`;
  };
  const upperPoints = upper.flatMap((value, index) => typeof value === "number" ? [point(value, index)] : []);
  const lowerPoints = lower.flatMap((value, index) => typeof value === "number" ? [point(value, index)] : []).reverse();
  if (!upperPoints.length || upperPoints.length !== lowerPoints.length) return "";
  return `M${upperPoints.join(" L")} L${lowerPoints.join(" L")} Z`;
}

function DemandForecastChart({ projection, controlTargetKw }: { projection: DemandProjection; controlTargetKw?: number }) {
  const [hover, setHover] = useState<{ index: number; x: number; right: boolean } | null>(null);
  const actualSeries: ChartSeries = { name: "实际需量", values: projection.actual, color: "#6488ed", width: 3 };
  const forecastSeries: ChartSeries = { name: "AI预测", values: projection.forecast, color: "#19e4c3", dashed: true, width: 2.8 };
  const targetSeries: ChartSeries = { name: "管控目标", values: projection.labels.map(() => controlTargetKw), color: "#91a0a5", dashed: true, width: 1.8 };
  const telemetryValues = chartValues([actualSeries, forecastSeries]);
  if (!telemetryValues.length) return <div className="chart-empty">暂无可用于需量预测的时序数据</div>;
  const values = chartValues([actualSeries, forecastSeries, targetSeries, { name: "下界", values: projection.lower, color: "" }, { name: "上界", values: projection.upper, color: "" }]);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const roughStep = Math.max(1, (rawMax - rawMin) / 4);
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalizedStep = roughStep / magnitude;
  const step = (normalizedStep <= 1 ? 1 : normalizedStep <= 2 ? 2 : normalizedStep <= 5 ? 5 : 10) * magnitude;
  const min = Math.max(0, Math.floor(rawMin / step) * step);
  const max = Math.max(min + step * 4, Math.ceil(rawMax / step) * step);
  const width = 900;
  const height = 300;
  const pointY = (value: number) => 14 + (1 - (value - min) / (max - min || 1)) * (height - 28);
  const ticks = Array.from({ length: 5 }, (_, index) => max - index * (max - min) / 4);
  const peakValue = projection.predictedMaxKw;
  const peakIndex = peakValue == null
    ? -1
    : projection.forecast.findIndex(value => typeof value === "number" && Math.abs(value - peakValue) < 0.001);
  const peakX = peakIndex < 0 ? 0 : peakIndex / Math.max(1, projection.labels.length - 1) * 100;
  const currentX = projection.currentSlot / Math.max(1, projection.labels.length - 1) * 100;
  const xLabels = Array.from({ length: 12 }, (_, index) => `${String(index * 2).padStart(2, "0")}:00`);
  const data: ChartData = { labels: projection.labels, unit: "kW", series: [actualSeries, forecastSeries, targetSeries] };
  return <div className="demand-forecast-chart">
    <div className="demand-y-axis"><b>kW</b>{ticks.map(value => <span key={value}>{format(value, 0)}</span>)}</div>
    <div className="demand-chart-plot interactive-chart" onMouseLeave={() => setHover(null)} onMouseMove={event => {
      const rect = event.currentTarget.getBoundingClientRect();
      const relativeX = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
      const index = Math.max(0, Math.min(data.labels.length - 1, Math.round(relativeX / rect.width * (data.labels.length - 1))));
      setHover({
        index,
        x: data.labels.length <= 1 ? 0 : index / (data.labels.length - 1) * rect.width,
        right: index > data.labels.length * 0.7,
      });
    }}>
      <div className="demand-chart-legend">
        <span className="actual"><i />实际需量</span>
        <span className="forecast"><i />AI预测</span>
        <span className="range"><i />预测区间</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="15分钟需量AI预测与管控曲线">
        {ticks.map(value => <line key={value} x1="0" x2={width} y1={pointY(value)} y2={pointY(value)} className="demand-grid-line" />)}
        <path d={demandRangePath(projection.lower, projection.upper, min, max, width, height)} className="demand-range-area" />
        <path d={linePath(projection.lower, min, max, width, height)} className="demand-range-line" />
        <path d={linePath(projection.upper, min, max, width, height)} className="demand-range-line" />
        <path d={linePath(targetSeries.values, min, max, width, height)} className="demand-target-line" />
        <path d={linePath(forecastSeries.values, min, max, width, height)} className="demand-ml-line" />
        <path d={linePath(actualSeries.values, min, max, width, height)} className="demand-actual-line" />
        {projection.actual.map((value, index) => typeof value === "number" && index % 4 === 0
          ? <circle key={index} cx={index / 95 * width} cy={pointY(value)} r="3.7" className="demand-actual-point" />
          : null)}
      </svg>
      <span className="demand-current-line" style={{ left: `${currentX}%` }}><b>当前</b></span>
      {peakIndex >= 0 && peakValue != null && <span className="demand-peak-label" style={{ left: `${peakX}%`, top: 39 + pointY(peakValue) }}>
        预计峰值 {format(peakValue, 0)} kW<i />
      </span>}
      <div className="demand-chart-axis">{xLabels.map(label => <span key={label}>{label}</span>)}</div>
      {hover && <><span className="chart-guide" style={{ left: hover.x }} />{data.series.map(series => {
        const value = series.values[hover.index];
        if (typeof value !== "number" || !Number.isFinite(value)) return null;
        return <span key={series.name} className="chart-dot" style={{ left: hover.x, top: 39 + pointY(value), background: series.color }} />;
      })}
        <div className={`chart-tooltip demand-tooltip ${hover.right ? "right" : ""}`} style={{ left: hover.x, top: 142 }}>
          <strong>{data.labels[hover.index]}</strong>
          {typeof projection.actual[hover.index] === "number" && <span><i style={{ background: actualSeries.color }} />实际需量<b>{format(projection.actual[hover.index], 1)} kW</b></span>}
          <span><i style={{ background: forecastSeries.color }} />AI预测<b>{format(projection.forecast[hover.index], 1)} kW</b></span>
          {typeof projection.lower[hover.index] === "number" && <span><i className="range-dot" />预测区间<b>{format(projection.lower[hover.index], 1)}–{format(projection.upper[hover.index], 1)} kW</b></span>}
          {controlTargetKw != null && <span><i style={{ background: targetSeries.color }} />管控目标<b>{format(controlTargetKw, 1)} kW</b></span>}
        </div>
      </>}
    </div>
  </div>;
}

function Ring({ value, label }: { value: number | undefined; label: string }) {
  const safe = Math.max(0, Math.min(100, value || 0));
  return <div className="score-ring" style={{ "--score": `${safe * 3.6}deg` } as React.CSSProperties}>
    <div><strong>{value === undefined ? "—" : Math.round(value)}</strong><span>{label}</span></div>
  </div>;
}

function insightToneIcon(tone: InsightTone, icon: string) {
  if (icon) return icon;
  if (tone === "amber") return "!";
  if (tone === "green") return "+";
  return "AI";
}

function InsightCard({ insight, open, evidenceOpen, onToggle, onEvidence, onAsk, onClose }: {
  insight: PageInsight;
  open: boolean;
  evidenceOpen: boolean;
  onToggle: () => void;
  onEvidence: () => void;
  onAsk: () => void;
  onClose: () => void;
}) {
  const daily = insight.id.startsWith("overview-");
  return <div className={`insight-card-shell ${daily ? "daily-insight-shell" : ""} ${open ? "open" : ""}`}>
    <button className={`insight-card ${insight.tone}`} type="button" onClick={onToggle} aria-expanded={open} aria-controls={`insight-detail-${insight.id}`}>
      <i>{insightToneIcon(insight.tone, insight.icon)}</i>
      <span><strong>{insight.title}</strong><small>{insight.summary}</small></span><b aria-hidden="true">›</b>
    </button>
    {open && <section className="insight-detail" id={`insight-detail-${insight.id}`} aria-label={`${insight.title}洞察详情`}>
      {daily ? <DailyInsightBody insight={insight} /> : <>
        <header><strong>{insight.title} · 洞察详情</strong><button type="button" onClick={onClose} aria-label="关闭洞察详情">×</button></header>
        <span className="insight-detail-badge">{insight.badge}</span>
        <h3>{insight.detailTitle}</h3>
        <p>{insight.detailSummary}</p>
        <dl>{insight.metrics.map(metric => <div key={metric.label}><dt>{metric.label}</dt><dd className={metric.tone || ""}>{metric.value}</dd></div>)}</dl>
      </>}
      {evidenceOpen && <div className="insight-evidence-panel"><strong>数据依据</strong>{insight.evidence.map(item => <div key={item.label}><span>{item.label}</span><b>{item.value}</b></div>)}</div>}
      <footer><button type="button" className={evidenceOpen ? "selected" : ""} onClick={onEvidence}>▤ {evidenceOpen ? "收起证据" : "查看证据"}</button><button type="button" onClick={onAsk}>··· 追问 AI</button></footer>
    </section>}
  </div>;
}

function DailyInsightBody({ insight }: { insight: PageInsight }) {
  const daily = insight.daily;
  return <div className="daily-insight-body">
    {insight.id === "overview-energy" && <div className="daily-panel-title"><strong>工厂能耗分析</strong><span>重点</span></div>}
    {daily?.headline && <div className="daily-value">
      <span>{daily.headline.label}<small>{daily.headline.unit || ""}</small></span>
      <div><b>{daily.headline.value} {daily.headline.unit && <small>{daily.headline.unit}</small>}</b>
        {daily.headline.change && <em className={daily.headline.changeTone === "amber" ? "amber" : ""}>{daily.headline.change}</em>}
      </div>
    </div>}
    {daily?.chart && <DailyLineChart data={daily.chart} />}
    {insight.id !== "overview-energy" && <>
      <p>{insight.detailSummary}</p>
      <div className="daily-kpis">{insight.metrics.map(metric =>
        <span key={metric.label}>{metric.label}<b className={metric.tone === "amber" ? "amber" : ""}>{metric.value}</b></span>
      )}</div>
    </>}
    {!!daily?.items?.length && <ul className={`daily-list ${insight.tone === "amber" ? "risk" : "action"}`}>
      {daily.items.map((item, index) => <li key={`${item.label}-${index}`}>{item.label}{item.value && <em className={item.tone === "green" ? "green" : ""}>{item.value}</em>}</li>)}
    </ul>}
    {daily?.footer && <div className="daily-summary-footer">
      <div><span>{daily.footer.label}</span><b>{daily.footer.value} {daily.footer.unit && <small>{daily.footer.unit}</small>}</b></div>
      {daily.footer.confidence && <div className="daily-confidence">数据证据 <strong>可信度 {daily.footer.confidence}</strong></div>}
    </div>}
    {daily?.note && <div className="daily-note">{daily.note}</div>}
  </div>;
}

function formatDateTime(value: string | number | undefined) {
  if (value === undefined) return "暂无时间信息";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "暂无时间信息" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function InsightRail({
  workspace, summary, snapshots, powerAnalysis, compressorAnalysis, summaryBusy, onRefresh, onAsk,
}: {
  workspace: Workspace;
  summary?: DailySummary;
  snapshots: DeviceSnapshot[];
  powerAnalysis: PowerAnalysisResult | null;
  compressorAnalysis: CompressorAnalysisResult | null;
  summaryBusy: boolean;
  onRefresh: () => void;
  onAsk: (prompt: string) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const overview = summary?.statistics.overview;
  const coverage = overview?.device_count ? overview.available_device_count / overview.device_count * 100 : snapshots.length ? 100 : undefined;
  const dataTrust = coverage === undefined ? "待评估" : coverage >= 95 ? "高" : coverage >= 75 ? "中" : "低";
  const demand = latestRecord(powerAnalysis?.metrics?.demand);
  const quality = latestRecord(powerAnalysis?.metrics?.quality);
  const compressorDevice = latestRecord(compressorAnalysis?.metrics?.devices);
  const compressorRealtime = latestRecord(compressorAnalysis?.metrics?.realtime);
  const compressorPressure = latestRecord(compressorAnalysis?.metrics?.pressure);
  const activeAlarms = snapshots.flatMap(snapshot => snapshot.alarms.map(alarm => ({ ...alarm, deviceName: snapshot.device.name })));
  const highAlarms = activeAlarms.filter(alarm => ["CRITICAL", "MAJOR"].includes(alarm.severity)).length;
  const powerWarnings = powerAnalysis?.warnings || [];
  const compressorWarnings = compressorAnalysis?.warnings || [];
  const warningCount = (summary?.warnings.length || 0) + powerWarnings.length + compressorWarnings.length;
  const maxThdi = quality?.thdi ? Math.max(...Object.values(quality.thdi).map(item => item.max || 0)) : undefined;
  const maxThdu = quality?.thdu ? Math.max(...Object.values(quality.thdu).map(item => item.max || 0)) : undefined;
  const demandMargin = demand?.declared_demand_kw != null && demand.max_demand_15m_kw != null ? demand.declared_demand_kw - demand.max_demand_15m_kw : undefined;
  const peakSpread = demand?.instantaneous_peak_kw != null && demand.average_load_kw != null ? demand.instantaneous_peak_kw - demand.average_load_kw : undefined;
  const savings = compressorAnalysis?.metrics?.savings_screening;
  const latestTs = snapshots.reduce((latest, snapshot) => Math.max(latest, ...Object.values(snapshot.telemetry).flat().map(sample => sample.ts)), 0);
  const scopeText = overview ? `${overview.available_device_count}/${overview.device_count} 台设备可用` : `${snapshots.length} 台设备`;
  const periodText = summary ? `${formatDateTime(summary.period_start)} 至 ${formatDateTime(summary.period_end)}` : "最近 24 小时";
  const baseEvidence: InsightEvidence[] = [
    { label: "对象范围", value: scopeText },
    { label: "数据截止", value: latestTs ? formatDateTime(latestTs) : "暂无有效时点" },
    { label: "数据来源", value: "统一工业时序数据接口" },
  ];
  const now = new Date();
  const todayStart = new Date(now);
  todayStart.setHours(0, 0, 0, 0);
  const yesterdayStart = new Date(todayStart);
  yesterdayStart.setDate(yesterdayStart.getDate() - 1);
  const monthStart = new Date(todayStart);
  monthStart.setDate(1);
  const meterSnapshots = snapshots.filter(snapshot => snapshot.device.type === "meter");
  const todayEnergyCurves = meterSnapshots.map(snapshot => ({
    name: snapshot.device.name,
    points: counterCurve(snapshot.insightHistory, "meter_SupWh", todayStart.getTime(), now.getTime()),
  })).filter(item => item.points.length > 1);
  const yesterdayEnergyCurves = meterSnapshots.map(snapshot => ({
    name: snapshot.device.name,
    points: counterCurve(snapshot.insightHistory, "meter_SupWh", yesterdayStart.getTime(), todayStart.getTime() - 1),
  })).filter(item => item.points.length > 1);
  const monthEnergyCurves = meterSnapshots.map(snapshot => ({
    name: snapshot.device.name,
    points: counterCurve(snapshot.monthHistory, "meter_SupWh", monthStart.getTime(), now.getTime()),
  })).filter(item => item.points.length > 1);
  const todayEnergyKwh = todayEnergyCurves.length
    ? todayEnergyCurves.reduce((total, curve) => total + (curve.points.at(-1)?.value || 0), 0)
    : overview?.energy_consumption_kwh ?? undefined;
  const yesterdayEnergyKwh = yesterdayEnergyCurves.length
    ? yesterdayEnergyCurves.reduce((total, curve) => total + (curve.points.at(-1)?.value || 0), 0)
    : undefined;
  const monthEnergyKwh = monthEnergyCurves.length
    ? monthEnergyCurves.reduce((total, curve) => total + (curve.points.at(-1)?.value || 0), 0)
    : undefined;
  const confidencePct = overview?.active_power_data_coverage != null
    ? overview.active_power_data_coverage * 100
    : coverage;
  const energyChangePct = todayEnergyKwh != null && yesterdayEnergyKwh
    ? (todayEnergyKwh - yesterdayEnergyKwh) / yesterdayEnergyKwh * 100
    : undefined;
  function aggregateEnergyCurves(
    curves: Array<{ points: Array<{ ts: number; value: number }> }>,
    dayStartTs: number,
    visibleEndTs: number,
  ): Array<number | null> {
    const intervalMs = 5 * 60 * 1000;
    const slotCount = 24 * 60 / 5;
    const finalSlot = Math.max(0, Math.min(slotCount - 1, Math.floor((visibleEndTs - dayStartTs) / intervalMs)));
    const totals = Array.from({ length: slotCount }, () => 0);
    const coverage = Array.from({ length: slotCount }, () => 0);
    for (const curve of curves) {
      let pointIndex = 0;
      let latestValue: number | undefined;
      for (let slot = 0; slot <= finalSlot; slot += 1) {
        const slotEndTs = dayStartTs + (slot + 1) * intervalMs - 1;
        while (pointIndex < curve.points.length && curve.points[pointIndex].ts <= slotEndTs) {
          latestValue = curve.points[pointIndex].value;
          pointIndex += 1;
        }
        if (latestValue == null) continue;
        totals[slot] += latestValue;
        coverage[slot] += 1;
      }
    }
    return totals.map((value, slot) => slot <= finalSlot && coverage[slot] > 0 ? value : null);
  }
  const todayEnergyValues = aggregateEnergyCurves(todayEnergyCurves, todayStart.getTime(), now.getTime());
  const yesterdayEnergyValues = aggregateEnergyCurves(yesterdayEnergyCurves, yesterdayStart.getTime(), todayStart.getTime() - 1);
  const energyChartPointCount = todayEnergyValues.filter((value): value is number => typeof value === "number").length;
  const energyLabels = Array.from({ length: 24 * 60 / 5 }, (_, slot) => {
    const totalMinutes = slot * 5;
    return `${String(Math.floor(totalMinutes / 60)).padStart(2, "0")}:${String(totalMinutes % 60).padStart(2, "0")}`;
  });
  const energyChart: ChartData | undefined = energyChartPointCount > 1 ? {
    labels: energyLabels,
    unit: "kWh",
    series: [
      { name: "今日", values: todayEnergyValues, color: "#20e6ef", width: 2.5 },
      ...(yesterdayEnergyValues.some(value => typeof value === "number") ? [{
        name: "昨日",
        values: yesterdayEnergyValues,
        color: "#829798",
        dashed: true,
        width: 2,
      }] : []),
    ],
  } : undefined;
  const allWarnings = [...(summary?.warnings || []), ...powerWarnings, ...compressorWarnings];
  const anomalyItems = [
    ...allWarnings.slice(0, 3).map(warning => ({
      label: warning.device_name ? `${warning.device_name}：${warning.message || "运行指标异常"}` : warning.message || "运行指标异常",
      value: warning.severity || "提醒",
      tone: "amber" as const,
    })),
    ...activeAlarms.slice(0, Math.max(0, 3 - allWarnings.length)).map(alarm => ({
      label: `${alarm.deviceName}：${alarm.type}`,
      value: alarm.severity,
      tone: "amber" as const,
    })),
  ];
  const operationAdvice = [
    ...(demandMargin != null && demandMargin < 0
      ? [{ label: "核验申报需量与当前 15 分钟滚动需量", value: `${format(Math.abs(demandMargin))} kW 超限` }]
      : []),
    ...(savings?.screening_savings_kwh != null
      ? [{ label: "复核空压机卸载能耗优化空间", value: `${format(savings.screening_savings_kwh)} kWh` }]
      : []),
    ...(anomalyItems.length
      ? [{ label: "按告警优先级核验运行异常", value: `${anomalyItems.length} 项` }]
      : []),
  ];

  const pageConfig = useMemo<{ title: string; statusLabel: string; scoreLabel: string; insights: PageInsight[] }>(() => {
    const overviewInsights: PageInsight[] = [
      { id: "overview-energy", icon: "Σ", tone: "cyan", title: "工厂能耗分析", badge: "今日能耗",
        summary: todayEnergyKwh != null ? `今日已用电 ${format(todayEnergyKwh)} kWh` : "等待日内时序电量数据",
        detailTitle: todayEnergyKwh != null ? "今日能耗由累计电量表计时序差值计算。" : "当前日内累计电量数据不足。",
        detailSummary: todayEnergyKwh != null ? `今日零点后可用数据用电量 ${format(todayEnergyKwh)} kWh；曲线按 5 分钟聚合，结论仅覆盖已接入电表。` : "至少需要两个有效累计电量读数才能计算今日总能耗，不使用固定值或功率瞬时值替代。",
        metrics: [
          { label: "平均有功功率", value: overview?.average_active_power_kw != null ? `${format(overview.average_active_power_kw)} kW` : "数据不足" },
          { label: "今日总能耗", value: todayEnergyKwh != null ? `${format(todayEnergyKwh)} kWh` : "数据不足", tone: "green" },
          { label: "数据可信度", value: dataTrust, tone: coverage !== undefined && coverage >= 75 ? "cyan" : "amber" },
        ], evidence: [{ label: "统计周期", value: `今日 00:00 至 ${now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}` }, ...baseEvidence],
        prompt: "展开工厂能耗分析，说明今日总能耗、昨日同期对比和时序数据依据",
        daily: {
          headline: {
            label: "今日总能耗",
            value: todayEnergyKwh != null ? format(todayEnergyKwh) : "数据不足",
            unit: todayEnergyKwh != null ? "kWh" : undefined,
            change: energyChangePct != null ? `${energyChangePct >= 0 ? "↑" : "↓"} ${format(Math.abs(energyChangePct))}% 同比昨日同期` : undefined,
            changeTone: energyChangePct != null && energyChangePct > 0 ? "amber" : "green",
          },
          chart: energyChart,
          footer: {
            label: "当月累计",
            value: monthEnergyKwh != null ? format(monthEnergyKwh / 1000, 2) : "数据不足",
            unit: monthEnergyKwh != null ? "MWh" : undefined,
            confidence: confidencePct != null ? `${format(confidencePct, 0)}%` : "待评估",
          },
          note: `累计电量计量点 · 5 分钟日内聚合 · ${energyChartPointCount} 个有效点`,
        } },
      { id: "overview-energy-risk", icon: "!", tone: demandMargin != null && demandMargin < 0 ? "amber" : "cyan", title: "能量风险预警", badge: "负荷预测风险",
        summary: demandMargin == null ? "等待需量风险与 AI 负荷预测数据" : demandMargin < 0 ? `需量裕度为负 ${format(demandMargin)} kW` : `需量剩余裕度 ${format(demandMargin)} kW`,
        detailTitle: demandMargin != null && demandMargin < 0 ? "当前存在需量越限风险，需要人工核验。" : "当前未发现确定性需量越限。",
        detailSummary: "风险结论由电表时序计算 15 分钟滚动需量并与申报需量比较，不使用瞬时功率替代需量，也不直接下发控制动作。",
        metrics: [
          { label: "15分钟最大需量", value: demand?.max_demand_15m_kw != null ? `${format(demand.max_demand_15m_kw)} kW` : "数据不足" },
          { label: "申报需量", value: demand?.declared_demand_kw != null ? `${format(demand.declared_demand_kw)} kW` : "未配置" },
          { label: "剩余裕度", value: demandMargin != null ? `${format(demandMargin)} kW` : "无法计算", tone: demandMargin != null && demandMargin < 0 ? "amber" : "green" },
        ], evidence: [...baseEvidence, { label: "判定口径", value: "meter_TotW 15 分钟滚动平均 vs 申报需量" }],
        prompt: "解释首页能量风险预警，说明15分钟需量、申报需量和时序数据依据",
        daily: {
          headline: {
            label: "当前需量裕度",
            value: demandMargin != null ? format(demandMargin) : "数据不足",
            unit: demandMargin != null ? "kW" : undefined,
          },
          items: demandMargin != null ? [{
            label: demandMargin < 0 ? "15 分钟最大需量已超过申报值" : "15 分钟最大需量仍低于申报值",
            value: `${format(Math.abs(demandMargin))} kW`,
            tone: demandMargin < 0 ? "amber" : "green",
          }] : [],
          note: "确定性规则 · 不包含尚未接入的未来负荷预测",
        } },
      { id: "overview-operation-anomaly", icon: "∿", tone: warningCount || activeAlarms.length ? "amber" : "green", title: "运行异常洞察", badge: "异常摘要",
        summary: warningCount || activeAlarms.length ? `发现 ${warningCount + activeAlarms.length} 条待关注信息` : "当前未发现确定性异常提醒",
        detailTitle: warningCount || activeAlarms.length ? "当前存在需要人工核验的运行提醒。" : "当前规则与活动告警未发现明显异常。",
        detailSummary: [...(summary?.warnings || []), ...powerWarnings, ...compressorWarnings][0]?.message || "继续保持监测，告警结论以当前数据范围为限。",
        metrics: [
          { label: "分析提醒", value: `${warningCount} 条`, tone: warningCount ? "amber" : "green" },
          { label: "活动告警", value: `${activeAlarms.length} 条`, tone: activeAlarms.length ? "amber" : "green" },
          { label: "高优先级", value: `${highAlarms} 条`, tone: highAlarms ? "amber" : "green" },
        ], evidence: [...baseEvidence, { label: "告警来源", value: "统一设备告警与确定性规则" }],
        prompt: "解释首页运行异常洞察，按优先级说明影响对象和证据",
        daily: {
          items: anomalyItems.length ? anomalyItems : [{ label: "当前数据窗口内未发现确定性异常或活动告警", value: "正常", tone: "green" }],
          note: `已核验 ${snapshots.length} 台设备，规则提醒 ${warningCount} 条，活动告警 ${activeAlarms.length} 条`,
        } },
      { id: "overview-operation-advice", icon: "✓", tone: savings?.screening_savings_kwh ? "green" : "cyan", title: "运行建议", badge: "AI 建议",
        summary: savings?.screening_savings_kwh != null ? `优先核验 ${format(savings.screening_savings_kwh)} kWh 节能筛查量` : "建议保持监测并补齐节能筛查数据",
        detailTitle: "当前建议均为只读分析建议，需要人工确认后执行。",
        detailSummary: "建议优先核验需量裕度、空压卸载能耗和异常告警；任何控制都必须创建 proposed 计划并通过审批。",
        metrics: [
          { label: "筛查节能量", value: savings?.screening_savings_kwh != null ? `${format(savings.screening_savings_kwh)} kWh` : "数据不足", tone: "green" },
          { label: "峰均差", value: peakSpread != null ? `${format(peakSpread)} kW` : "数据不足" },
          { label: "控制方式", value: "人工审批", tone: "cyan" },
        ], evidence: [...baseEvidence, { label: "安全边界", value: "只读建议，不直接执行 RPC" }],
        prompt: "根据首页指标给出运行建议，说明哪些需要人工确认和审批",
        daily: {
          items: operationAdvice.length ? operationAdvice : [{ label: "当前无量化优化建议，继续采集运行数据", value: "监测中", tone: "green" }],
          note: "建议来自当前确定性指标，执行前必须人工确认",
        } },
      { id: "overview-confirmation", icon: "□", tone: warningCount || demandMargin != null && demandMargin < 0 ? "amber" : "muted", title: "待确认事项", badge: "人工确认",
        summary: warningCount || demandMargin != null && demandMargin < 0 ? "存在需值班人员确认的风险与建议" : "当前暂无强制确认事项",
        detailTitle: "待确认事项用于承接风险预警和运行建议。",
        detailSummary: "当前包括需量风险核验、空压节能筛查复核、活动告警处置确认；确认后仍需走服务端审批和审计流程。",
        metrics: [
          { label: "需量风险确认", value: demandMargin != null && demandMargin < 0 ? "需要" : "暂无", tone: demandMargin != null && demandMargin < 0 ? "amber" : "green" },
          { label: "异常确认", value: warningCount + activeAlarms.length ? `${warningCount + activeAlarms.length} 项` : "暂无" },
          { label: "节能建议确认", value: savings?.screening_savings_kwh ? "需要复核" : "待数据", tone: savings?.screening_savings_kwh ? "cyan" : "muted" },
        ], evidence: [...baseEvidence, { label: "闭环状态", value: "待接入责任人、执行记录和效果验证" }],
        prompt: "列出首页待确认事项，按风险、异常和运行建议分类说明",
        daily: {
          items: [
            ...(demandMargin != null && demandMargin < 0 ? [{ label: "确认需量越限风险及申报值", value: "待确认" }] : []),
            ...(anomalyItems.length ? [{ label: "确认设备异常与活动告警", value: `${anomalyItems.length} 项` }] : []),
            ...(savings?.screening_savings_kwh ? [{ label: "复核空压节能筛查量", value: `${format(savings.screening_savings_kwh)} kWh` }] : []),
          ],
          note: "所有控制操作仍需 proposed 计划、人工审批和服务端策略校验",
        } },
    ];

    const demandInsights: PageInsight[] = [
      { id: "demand-peak", icon: "!", tone: demandMargin != null && demandMargin < 0 ? "amber" : "cyan", title: "峰值风险", badge: "15 分钟需量",
        summary: demandMargin == null ? "需量控制目标或滚动需量数据不足" : demandMargin < 0 ? `已超需量控制目标 ${format(Math.abs(demandMargin))} kW` : `距需量控制目标尚余 ${format(demandMargin)} kW`,
        detailTitle: demandMargin == null ? "当前不能完成需量越限判断。" : demandMargin < 0 ? "15 分钟滚动需量已超过申报值。" : "当前 15 分钟滚动需量未超过申报值。",
        detailSummary: "需量风险只使用 15 分钟滚动需量判定，不以实时功率或周期不明的寄存器替代。",
        metrics: [{ label: "最大滚动需量", value: demand?.max_demand_15m_kw != null ? `${format(demand.max_demand_15m_kw)} kW` : "数据不足" }, { label: "需量控制目标", value: demand?.declared_demand_kw != null ? `${format(demand.declared_demand_kw)} kW` : "未配置" }, { label: "剩余裕度", value: demandMargin != null ? `${format(demandMargin)} kW` : "无法计算", tone: demandMargin != null && demandMargin < 0 ? "amber" : "green" }],
        evidence: [...baseEvidence, { label: "判定口径", value: "15 分钟滚动平均 vs 需量控制目标" }], prompt: "解释当前15分钟需量风险、需量控制目标裕度和判断依据" },
      { id: "demand-shaving", icon: "∿", tone: peakSpread != null && peakSpread > 0 ? "green" : "muted", title: "削峰机会", badge: "峰值优化线索",
        summary: peakSpread != null ? `峰值高于平均负荷 ${format(peakSpread)} kW` : "等待峰值与平均负荷数据",
        detailTitle: peakSpread != null ? "负荷曲线存在可进一步核验的峰均差。" : "当前无法识别可量化的削峰空间。",
        detailSummary: "该结果仅表示历史负荷差异，不等同于可调负荷容量或可直接执行的削峰量。",
        metrics: [{ label: "瞬时峰值", value: demand?.instantaneous_peak_kw != null ? `${format(demand.instantaneous_peak_kw)} kW` : "数据不足" }, { label: "平均负荷", value: demand?.average_load_kw != null ? `${format(demand.average_load_kw)} kW` : "数据不足" }, { label: "峰均比", value: demand?.peak_average_ratio != null ? format(demand.peak_average_ratio, 3) : "数据不足", tone: "cyan" }],
        evidence: [...baseEvidence, { label: "分析边界", value: "历史峰值线索，未建模可调资源" }], prompt: "分析负荷峰均差和削峰机会，但不要把历史峰值差当作可调容量" },
      { id: "demand-execution", icon: "≡", tone: "muted", title: "执行状态", badge: "安全边界", summary: "当前页面仅提供只读分析",
        detailTitle: "AI 不会直接执行需量控制。", detailSummary: "任何设备控制都必须先创建 proposed 计划，再经人工审批和服务端策略校验。",
        metrics: [{ label: "当前能力", value: "只读分析" }, { label: "审批要求", value: "人工审批", tone: "cyan" }, { label: "自动执行", value: "禁止", tone: "amber" }],
        evidence: [...baseEvidence, { label: "控制链路", value: "计划 → 审批 → 策略校验 → RPC" }], prompt: "说明当前需量分析可以做什么，以及控制计划的审批安全边界" },
      { id: "demand-month", icon: "月", tone: "muted", title: "月度判断", badge: "统计周期", summary: "当前分析窗口不足以形成月度结论",
        detailTitle: "月度需量判断需要完整计费周期数据。", detailSummary: "当前页面使用最近 24 小时数据，不会将短周期结果伪装成本月最大需量或未来预测。",
        metrics: [{ label: "当前窗口", value: "最近 24 小时" }, { label: "月度最大需量", value: "数据不足" }, { label: "未来预测", value: "未接入" }],
        evidence: [...baseEvidence, { label: "所需数据", value: "完整计费周期与需量预测结果" }], prompt: "说明为什么当前不能形成月度需量判断，以及还需要哪些数据" },
    ];

    const qualityInsights: PageInsight[] = [
      { id: "quality-harmonic", icon: "∿", tone: maxThdi != null && maxThdi > 0 ? "amber" : "muted", title: "谐波风险", badge: "谐波筛查", summary: maxThdi != null ? `监测窗口最大 THDi ${format(maxThdi, 2)}%` : "等待谐波监测数据",
        detailTitle: maxThdi != null ? "已形成谐波确定性筛查结果。" : "当前无法判断谐波风险。", detailSummary: "平台提醒不直接等同于适用标准超限，仍需结合 PCC、现场接线与采样质量核验。",
        metrics: [{ label: "最大 THDi", value: maxThdi != null ? `${format(maxThdi, 2)}%` : "数据不足", tone: "amber" }, { label: "最大 THDu", value: maxThdu != null ? `${format(maxThdu, 2)}%` : "数据不足" }, { label: "数据可信度", value: dataTrust, tone: "cyan" }],
        evidence: [...baseEvidence, { label: "分析来源", value: "三相 THD 确定性工具" }], prompt: "解释当前谐波风险、三相THD结果和现场核验边界" },
      { id: "quality-reactive", icon: "φ", tone: quality?.power_factor?.latest != null && quality.power_factor.latest < .95 ? "amber" : "green", title: "无功优化", badge: "功率因数", summary: quality?.power_factor?.latest != null ? `当前功率因数 ${format(quality.power_factor.latest, 3)}` : "等待功率因数数据",
        detailTitle: quality?.power_factor?.latest != null && quality.power_factor.latest < .95 ? "功率因数偏低，建议核查无功补偿状态。" : "当前功率因数未出现明显偏低线索。", detailSummary: "当前缺少补偿柜容量与无功功率数据，不计算补偿量或节省费用。",
        metrics: [{ label: "当前值", value: format(quality?.power_factor?.latest, 3) }, { label: "窗口最低", value: format(quality?.power_factor?.min, 3) }, { label: "窗口最高", value: format(quality?.power_factor?.max, 3), tone: "green" }],
        evidence: [...baseEvidence, { label: "优化边界", value: "仅提示功率因数线索" }], prompt: "分析当前功率因数和无功优化线索，说明缺失的数据条件" },
      { id: "quality-voltage", icon: "V", tone: powerWarnings.length ? "amber" : "green", title: "电压事件", badge: "质量事件", summary: powerWarnings.length ? `${powerWarnings.length} 条电力质量提醒待核验` : "当前未产生电力质量提醒",
        detailTitle: powerWarnings[0]?.message || "当前确定性工具未产生电压质量提醒。", detailSummary: "事件结论基于已执行的电压、不平衡与持续时间能力，不补造缺失相数据。",
        metrics: [{ label: "电力提醒", value: `${powerWarnings.length} 条`, tone: powerWarnings.length ? "amber" : "green" }, { label: "电流不平衡", value: quality?.current_unbalance?.max != null ? `${format(quality.current_unbalance.max, 2)}%` : "数据不足" }, { label: "活动告警", value: `${activeAlarms.length} 条` }],
        evidence: [...baseEvidence, { label: "事件来源", value: "电力确定性规则与活动告警" }], prompt: "解释当前电压和不平衡事件，列出影响与证据" },
      { id: "quality-effect", icon: "✓", tone: "muted", title: "治理效果", badge: "效果基线", summary: "尚未建立治理前后对比基线",
        detailTitle: "当前不能声称治理后指标已改善。", detailSummary: "需要治理动作、投运时间和同口径前后窗口，才能评价 APF、SVG 或补偿策略效果。",
        metrics: [{ label: "治理动作", value: "未接入" }, { label: "对比基线", value: "未建立" }, { label: "当前监测", value: maxThdi != null ? "可用" : "数据不足", tone: "cyan" }],
        evidence: [...baseEvidence, { label: "验效要求", value: "同对象、同口径、治理前后窗口" }], prompt: "说明电能质量治理效果评估需要哪些基线和证据" },
    ];

    const compressorInsights: PageInsight[] = [
      { id: "compressor-group", icon: "◎", tone: compressorDevice?.unload_rate_pct != null && compressorDevice.unload_rate_pct > 20 ? "amber" : "cyan", title: "群控机会", badge: "运行协同", summary: compressorDevice?.unload_rate_pct != null ? `当前单机卸载率 ${format(compressorDevice.unload_rate_pct, 1)}%` : "群控数据范围不足",
        detailTitle: "当前仅能提供已接入空压机的运行线索。", detailSummary: "未形成多机负荷排序时，不建议具体设备退出或自动执行群控。",
        metrics: [{ label: "加载率", value: compressorDevice?.load_rate_pct != null ? `${format(compressorDevice.load_rate_pct, 1)}%` : "数据不足" }, { label: "卸载率", value: compressorDevice?.unload_rate_pct != null ? `${format(compressorDevice.unload_rate_pct, 1)}%` : "数据不足", tone: "amber" }, { label: "自动群控", value: "禁止", tone: "amber" }],
        evidence: [...baseEvidence, { label: "分析边界", value: "当前设备范围内的只读运行分析" }], prompt: "分析空压机加载卸载和群控机会，不要给出未经审批的控制动作" },
      { id: "compressor-pressure", icon: "P", tone: compressorWarnings.length ? "amber" : "green", title: "压力优化", badge: "供气压力", summary: compressorRealtime?.supply_pressure_mpa != null ? `当前母管压力 ${format(compressorRealtime.supply_pressure_mpa, 3)} MPa` : "等待压力数据",
        detailTitle: compressorWarnings[0]?.message || "当前压力工具未产生明显异常提醒。", detailSummary: "压力下调幅度必须结合设备约束与末端需求验证，当前不直接给出控制设定值。",
        metrics: [{ label: "当前压力", value: compressorRealtime?.supply_pressure_mpa != null ? `${format(compressorRealtime.supply_pressure_mpa, 3)} MPa` : "数据不足" }, { label: "窗口均值", value: compressorPressure?.avg_mpa != null ? `${format(compressorPressure.avg_mpa, 3)} MPa` : "数据不足" }, { label: "压力波动", value: compressorPressure?.p95_p5_mpa != null ? `${format(compressorPressure.p95_p5_mpa, 3)} MPa` : "数据不足" }],
        evidence: [...baseEvidence, { label: "分析来源", value: "空压压力波动确定性工具" }], prompt: "分析当前供气压力、波动和压力优化边界" },
      { id: "compressor-leak", icon: "○", tone: compressorWarnings.length ? "amber" : "muted", title: "泄漏风险", badge: "泄漏筛查", summary: compressorWarnings.length ? "存在空压异常提醒，建议核查非生产时段" : "当前没有独立泄漏率结果",
        detailTitle: "泄漏结论需要有效流量和生产时段配置。", detailSummary: "现有结果仅作筛查，不能把缺失流量补零或将估算直接作为正式泄漏率。",
        metrics: [{ label: "异常提醒", value: `${compressorWarnings.length} 条`, tone: compressorWarnings.length ? "amber" : "green" }, { label: "筛查泄漏率", value: "数据不足" }, { label: "现场核验", value: "需要" }],
        evidence: [...baseEvidence, { label: "所需数据", value: "流量、生产时段与停产基线" }], prompt: "说明当前空压泄漏筛查结果和还需核验的数据" },
      { id: "compressor-effect", icon: "↘", tone: savings?.screening_savings_kwh ? "green" : "muted", title: "运行效果", badge: "当期表现", summary: compressorAnalysis?.metrics?.specific_power?.average_kw_per_m3_min != null ? `系统比功率 ${format(compressorAnalysis.metrics.specific_power.average_kw_per_m3_min, 3)}` : "等待比功率结果",
        detailTitle: "当前只展示同一分析窗口内的确定性指标。", detailSummary: "未建立昨日或治理前基线时，不声称比功率改善百分比。",
        metrics: [{ label: "系统比功率", value: compressorAnalysis?.metrics?.specific_power?.average_kw_per_m3_min != null ? `${format(compressorAnalysis.metrics.specific_power.average_kw_per_m3_min, 3)} kW/(m³/min)` : "数据不足" }, { label: "筛查节能量", value: savings?.screening_savings_kwh != null ? `${format(savings.screening_savings_kwh)} kWh` : "数据不足", tone: "green" }, { label: "数据可信度", value: dataTrust, tone: "cyan" }],
        evidence: [...baseEvidence, { label: "效果边界", value: "未建立跨期基线" }], prompt: "解释当前空压系统比功率、节能筛查和效果评价边界" },
    ];

    const carbonInsights: PageInsight[] = [
      { id: "carbon-intensity", icon: "∿", tone: "muted", title: "排放强度", badge: "核算条件", summary: "缺少产量与排放因子，暂不可计算", detailTitle: "当前不具备正式排放强度计算条件。", detailSummary: "单位产值碳排需要可审计排放量与产值或产量口径，平台不会用能耗直接冒充碳强度。", metrics: [{ label: "能源数据", value: overview?.energy_consumption_kwh != null ? "已具备" : "待补充", tone: "green" }, { label: "排放因子", value: "未接入", tone: "amber" }, { label: "产量数据", value: "未接入", tone: "amber" }], evidence: [...baseEvidence, { label: "核算结论", value: "数据条件不足" }], prompt: "说明排放强度为什么暂不可计算，以及需要补充哪些数据" },
      { id: "carbon-opportunity", icon: "↓", tone: savings?.screening_savings_kwh ? "green" : "muted", title: "减排机会", badge: "节电线索", summary: savings?.screening_savings_kwh != null ? `发现 ${format(savings.screening_savings_kwh)} kWh 节电筛查量` : "等待可核验的节电筛查结果", detailTitle: "节电量尚不能直接换算为减排量。", detailSummary: "接入适用排放因子和核算边界后，才能将已验证节电量换算为 tCO₂e。", metrics: [{ label: "节电筛查量", value: savings?.screening_savings_kwh != null ? `${format(savings.screening_savings_kwh)} kWh` : "数据不足", tone: "green" }, { label: "减排量", value: "不可计算" }, { label: "正式核验", value: "尚未完成" }], evidence: [...baseEvidence, { label: "换算状态", value: "排放因子未接入" }], prompt: "分析当前节电线索与减排量换算之间的边界" },
      { id: "carbon-factor", icon: "↻", tone: "amber", title: "因子更新", badge: "版本管理", summary: "排放因子数据源与版本尚未接入", detailTitle: "当前没有可审计的电网排放因子版本。", detailSummary: "正式核算前需明确区域、适用年份、发布机构和生效日期。", metrics: [{ label: "因子来源", value: "未配置" }, { label: "版本日期", value: "未配置" }, { label: "适用区域", value: "未配置" }], evidence: [...baseEvidence, { label: "接入要求", value: "来源、版本、区域、生效日期" }], prompt: "说明碳排因子接入需要管理哪些版本信息" },
      { id: "carbon-quality", icon: "▤", tone: coverage !== undefined && coverage >= 95 ? "green" : "amber", title: "数据质量", badge: "核算准备度", summary: coverage !== undefined ? `工业设备数据覆盖 ${format(coverage, 0)}%` : "等待工业数据覆盖结果", detailTitle: "能源数据覆盖不代表碳核算链路已经完整。", detailSummary: "还需补充组织边界、排放因子、产量和基准期，才能形成可复核碳数据。", metrics: [{ label: "设备覆盖", value: coverage !== undefined ? `${format(coverage, 0)}%` : "待评估", tone: "green" }, { label: "统计期电量", value: overview?.energy_consumption_kwh != null ? "可用" : "数据不足" }, { label: "碳核算状态", value: "未就绪", tone: "amber" }], evidence: [...baseEvidence, { label: "缺失维度", value: "边界、因子、产量、基线" }], prompt: "评估当前碳核算数据质量和缺失项" },
    ];

    const eventInsights: PageInsight[] = [
      { id: "events-priority", icon: "!", tone: highAlarms ? "amber" : "cyan", title: "优先处置", badge: "事件优先级", summary: highAlarms ? `${highAlarms} 条高优先级活动告警` : activeAlarms.length ? `${activeAlarms.length} 条活动告警待确认` : "当前没有活动告警", detailTitle: highAlarms ? "高优先级事件需要先完成人工确认。" : "当前活动事件未出现高优先级告警。", detailSummary: activeAlarms[0] ? `${activeAlarms[0].deviceName} · ${activeAlarms[0].type}` : "继续保持事件监测与证据留存。", metrics: [{ label: "活动事件", value: `${activeAlarms.length} 条` }, { label: "高优先级", value: `${highAlarms} 条`, tone: highAlarms ? "amber" : "green" }, { label: "影响设备", value: `${new Set(activeAlarms.map(item => item.deviceName)).size} 台` }], evidence: [...baseEvidence, { label: "事件来源", value: "统一告警接口" }], prompt: "按优先级解释当前活动告警、影响设备和处置证据" },
      { id: "events-quality", icon: "∿", tone: powerWarnings.length ? "amber" : "green", title: "治理异常", badge: "电力质量", summary: powerWarnings.length ? `${powerWarnings.length} 条电力治理提醒` : "当前没有电力治理提醒", detailTitle: powerWarnings[0]?.message || "当前电力确定性工具未产生异常。", detailSummary: "质量提醒不直接等同于标准超限，需结合现场与适用标准确认。", metrics: [{ label: "电力提醒", value: `${powerWarnings.length} 条`, tone: powerWarnings.length ? "amber" : "green" }, { label: "最大 THDi", value: maxThdi != null ? `${format(maxThdi, 2)}%` : "数据不足" }, { label: "功率因数", value: format(quality?.power_factor?.latest, 3) }], evidence: [...baseEvidence, { label: "分析来源", value: "电能质量确定性工具" }], prompt: "解释当前治理异常及其电能质量证据" },
      { id: "events-saving", icon: "↓", tone: compressorWarnings.length ? "amber" : "green", title: "节能机会", badge: "空压事件", summary: compressorWarnings.length ? `${compressorWarnings.length} 条空压节能线索` : "当前没有空压异常提醒", detailTitle: compressorWarnings[0]?.message || "当前空压确定性工具未产生节能异常。", detailSummary: "节能线索需要现场核验，不能直接作为控制执行依据。", metrics: [{ label: "空压提醒", value: `${compressorWarnings.length} 条`, tone: compressorWarnings.length ? "amber" : "green" }, { label: "卸载率", value: compressorDevice?.unload_rate_pct != null ? `${format(compressorDevice.unload_rate_pct, 1)}%` : "数据不足" }, { label: "筛查节能量", value: savings?.screening_savings_kwh != null ? `${format(savings.screening_savings_kwh)} kWh` : "数据不足" }], evidence: [...baseEvidence, { label: "分析来源", value: "空压运行与节能筛查" }], prompt: "解释当前空压节能事件、影响和证据" },
      { id: "events-verify", icon: "✓", tone: "muted", title: "验证提醒", badge: "闭环状态", summary: "事件责任、执行与效果验证尚未接入", detailTitle: "当前页面只展示活动告警与分析结果。", detailSummary: "没有正式闭环状态时，不会虚构待执行、执行中或已验证数量。", metrics: [{ label: "事件发现", value: activeAlarms.length ? "已接入" : "暂无事件", tone: "green" }, { label: "责任确认", value: "未接入" }, { label: "效果验证", value: "未接入" }], evidence: [...baseEvidence, { label: "闭环缺口", value: "责任人、执行记录、验证窗口" }], prompt: "说明当前智能事件闭环还缺少哪些责任、执行和验证数据" },
    ];

    if (workspace === "demand") return { title: "AI 需量洞察", statusLabel: "需量数据状态", scoreLabel: "数据覆盖", insights: demandInsights };
    if (workspace === "quality") return { title: "AI 治理洞察", statusLabel: "电能质量数据", scoreLabel: "数据覆盖", insights: qualityInsights };
    if (workspace === "compressor") return { title: "AI 节能洞察", statusLabel: "空压数据状态", scoreLabel: "数据覆盖", insights: compressorInsights };
    if (workspace === "carbon") return { title: "AI 碳排洞察", statusLabel: "碳核算准备度", scoreLabel: "能源覆盖", insights: carbonInsights };
    if (workspace === "events") return { title: "AI 事件洞察", statusLabel: "事件数据状态", scoreLabel: "数据覆盖", insights: eventInsights };
    return { title: "AI 每日洞察", statusLabel: "工业数据覆盖", scoreLabel: "覆盖率", insights: overviewInsights };
  }, [activeAlarms, anomalyItems, baseEvidence, compressorDevice, compressorPressure, compressorRealtime, compressorWarnings, confidencePct, coverage, dataTrust, demand, demandMargin, energyChangePct, energyChart, energyChartPointCount, highAlarms, maxThdi, maxThdu, monthEnergyKwh, now, operationAdvice, overview, peakSpread, periodText, powerWarnings, savings, snapshots.length, summary?.warnings, todayEnergyKwh, warningCount, workspace]);

  useEffect(() => { setSelectedId(null); setEvidenceOpen(false); }, [workspace]);
  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) { if (event.key === "Escape") { setSelectedId(null); setEvidenceOpen(false); } }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function toggleInsight(id: string) {
    setSelectedId(current => current === id ? null : id);
    setEvidenceOpen(false);
  }

  return <aside className="insight-rail">
    <div className="rail-score">
      <div><p>{pageConfig.statusLabel}</p><Ring value={coverage} label={pageConfig.scoreLabel} /></div>
      <dl><div><dt>设备</dt><dd>{overview ? `${overview.available_device_count}/${overview.device_count}` : snapshots.length || "—"}</dd></div><div><dt>提醒</dt><dd>{warningCount + activeAlarms.length}</dd></div></dl>
    </div>
    <div className="rail-heading"><span>✦</span><h2>{pageConfig.title}</h2><small>{summary ? summary.summary_date : "实时分析"}</small>{workspace === "overview" && <button type="button" onClick={onRefresh} disabled={summaryBusy} title="重新生成每日摘要" aria-label="重新生成每日摘要">{summaryBusy ? "…" : "↻"}</button>}</div>
    <div className="insight-list">{pageConfig.insights.map(insight => <InsightCard key={insight.id} insight={insight} open={selectedId === insight.id} evidenceOpen={selectedId === insight.id && evidenceOpen} onToggle={() => toggleInsight(insight.id)} onEvidence={() => setEvidenceOpen(current => !current)} onClose={() => { setSelectedId(null); setEvidenceOpen(false); }} onAsk={() => onAsk(insight.prompt)} />)}</div>
  </aside>;
}

function EnergyMap({ meter, ems, compressor }: { meter?: DeviceSnapshot; ems?: DeviceSnapshot; compressor?: DeviceSnapshot }) {
  const meterPower = valueOf(meter?.telemetry, "meter_TotW");
  const emsPower = valueOf(ems?.telemetry, "power_kw");
  const soc = valueOf(ems?.telemetry, "soc");
  const pressure = valueOf(compressor?.telemetry, "air_comp_supply_pressure");
  return <section className="energy-map">
    <div className="map-title"><h2>源网荷储</h2><span>统一工业数据接口</span></div>
    <div className="energy-node grid-node"><i>电网</i><strong>{format(meterPower)} <small>kW</small></strong><span>实时进线功率</span></div>
    <div className="energy-node ems-node"><i>EMS</i><strong>{format(emsPower)} <small>kW</small></strong><span>SOC {format(soc)}%</span></div>
    <div className="factory-core"><div className="factory-bars"><i /><i /><i /><i /></div><strong>能源运营中心</strong><span>AI 专家协同在线</span></div>
    <div className="energy-node load-node"><i>负荷</i><strong>{format(meterPower)} <small>kW</small></strong><span>关键计量</span></div>
    <div className="energy-node air-node"><i>空压</i><strong>{format(pressure, 3)} <small>MPa</small></strong><span>供气母管</span></div>
    <div className="connector connector-a" /><div className="connector connector-b" /><div className="connector connector-c" /><div className="connector connector-d" />
  </section>;
}

function MetricTile({ icon, label, value, unit, note, tone = "cyan" }: { icon: string; label: string; value: string; unit: string; note: string; tone?: "cyan" | "green" | "amber" }) {
  return <article className={`metric-tile ${tone}`}><header><i>{icon}</i><span>{label}</span></header><strong>{value} <small>{unit}</small></strong><p>{note}</p></article>;
}

function Overview({ snapshots, powerAnalysis, compressorAnalysis, loadForecast }: { snapshots: DeviceSnapshot[]; powerAnalysis: PowerAnalysisResult | null; compressorAnalysis: CompressorAnalysisResult | null; loadForecast: DemandForecastResponse | null }) {
  const meter = snapshots.find(row => row.device.type === "meter");
  const ems = snapshots.find(row => row.device.type === "ems");
  const compressor = snapshots.find(row => row.device.type === "compressor");
  const power = valueOf(meter?.telemetry, "meter_TotW");
  const pf = valueOf(meter?.telemetry, "meter_TotPF");
  const energy = valueOf(meter?.telemetry, "meter_SupWh");
  const demand = latestRecord(powerAnalysis?.metrics?.demand);
  const realtime = latestRecord(compressorAnalysis?.metrics?.realtime);
  const limitKw = demand?.declared_demand_kw ?? undefined;
  const riskStart = loadForecast && limitKw != null
    ? loadForecast.points.findIndex((point, index) => index >= loadForecast.current_slot && point.prediction_kw > limitKw)
    : -1;
  let riskEnd = riskStart;
  if (loadForecast && limitKw != null && riskStart >= 0) {
    while (riskEnd + 1 < loadForecast.points.length && loadForecast.points[riskEnd + 1].prediction_kw > limitKw) riskEnd += 1;
  }
  const riskWindow = limitKw == null
    ? "限值未配置"
    : riskStart < 0 || !loadForecast
      ? "暂无"
      : `${loadForecast.points[riskStart].label}-${riskEnd >= 95 ? "24:00" : loadForecast.points[riskEnd + 1].label}`;
  return <div className="overview-workspace">
    <EnergyMap meter={meter} ems={ems} compressor={compressor} />
    <section className="trend-panel forecast-panel">
      <div className="section-head overview-forecast-header">
        <div><p>AI FORECAST</p><h3>今日AI负荷预测曲线</h3></div>
        <span>模拟工况训练 · 实时时序校准 · 悬浮查看数值</span>
      </div>
      <ForecastLineChart forecast={loadForecast} limitKw={limitKw} />
      <div className="forecast-stats"><span>今日峰值预测 <b>{format(loadForecast?.peak_prediction_kw)} <small>kW</small></b></span><span>风险时段 <b className={riskStart >= 0 ? "risk" : ""}>{riskWindow}</b></span><span>置信度 <b>{loadForecast?.quality_grade || "计算中"}</b></span></div>
    </section>
    <aside className="metric-rail">
      <MetricTile icon="∿" label="当前负荷" value={format(power)} unit="kW" note={demand?.max_demand_15m_kw != null ? `15分钟最大需量 ${format(demand.max_demand_15m_kw)} kW` : "需量计算中"} />
      <MetricTile icon="Σ" label="累计正向电量" value={format(energy)} unit="kWh" note="电表累计寄存器读数" tone="green" />
      <MetricTile icon="φ" label="功率因数" value={format(pf, 3)} unit="" note={pf == null ? "暂无有效数据" : "平台确定性监测"} />
      <MetricTile icon="P" label="空压供气压力" value={format(realtime?.supply_pressure_mpa, 3)} unit="MPa" note={realtime?.running == null ? "状态待获取" : realtime.running ? "空压机运行中" : "空压机已停止"} tone="amber" />
    </aside>
  </div>;
}

function InsightList({ title, warnings, empty }: { title: string; warnings?: Array<{ message?: string; severity?: string }>; empty: string }) {
  return <section className="expert-insights"><div className="section-head"><div><p>AI 专家洞察</p><h3>{title}</h3></div><span>确定性工具结果</span></div>
    <div>{warnings?.length ? warnings.slice(0, 4).map((warning, index) => <article key={index}><i className={warning.severity === "high" ? "danger" : "warning"}>!</i><p>{warning.message || "检测到需要关注的指标"}</p></article>) : <article><i>✓</i><p>{empty}</p></article>}</div>
  </section>;
}

function DemandWorkspace({ analysis, snapshot, forecast, onAsk }: { analysis: PowerAnalysisResult | null; snapshot?: DeviceSnapshot; forecast: DemandForecastResponse | null; onAsk: (prompt: string) => void }) {
  const metric = latestRecord(analysis?.metrics?.demand);
  const projection = useMemo(
    () => forecast ? machineDemandProjection(forecast) : buildDemandProjection(snapshot?.insightHistory),
    [forecast, snapshot?.insightHistory],
  );
  const currentDemandKw = projection.currentDemandKw ?? metric?.max_demand_15m_kw ?? undefined;
  const predictedMaxKw = projection.predictedMaxKw ?? metric?.max_demand_15m_kw ?? undefined;
  const declaredTargetKw = metric?.declared_demand_kw ?? undefined;
  const suggestedTargetKw = declaredTargetKw != null
    ? declaredTargetKw
    : predictedMaxKw != null
      ? Math.ceil(predictedMaxKw * 1.08 / 10) * 10
      : undefined;
  const [controlTargetKw, setControlTargetKw] = useState(suggestedTargetKw ?? 0);
  useEffect(() => {
    setControlTargetKw(suggestedTargetKw ?? 0);
  }, [snapshot?.device.id, declaredTargetKw, forecast?.forecast_date]);
  const targetAvailable = controlTargetKw > 0;
  const margin = targetAvailable && predictedMaxKw != null ? controlTargetKw - predictedMaxKw : undefined;
  const riskIndex = targetAvailable
    ? projection.forecast.findIndex((value, index) => index >= projection.currentSlot && typeof value === "number" && value > controlTargetKw)
    : -1;
  const riskTime = riskIndex >= 0 ? projection.labels[riskIndex] : undefined;
  const referenceKw = Math.max(currentDemandKw || 0, predictedMaxKw || 0, suggestedTargetKw || 0, 100);
  const sliderStep = referenceKw < 100 ? 1 : 10;
  const sliderMin = Math.max(sliderStep, Math.floor(referenceKw * 0.6 / sliderStep) * sliderStep);
  const sliderMax = Math.max(sliderMin + sliderStep * 10, Math.ceil(referenceKw * 1.4 / sliderStep) * sliderStep);
  const advicePrompt = [
    "基于当前15分钟需量数据生成管控建议，只做预警和方案推演，不执行设备控制。",
    `当前需量：${format(currentDemandKw)} kW`,
    `预测最大需量：${format(predictedMaxKw)} kW`,
    `管控目标：${targetAvailable ? format(controlTargetKw) : "未设置"} kW`,
    `预测剩余裕度：${format(margin)} kW`,
    `首个预计超限时刻：${riskTime || "未发现"}`,
  ].join("；");
  return <div className="domain-workspace">
    <div className="domain-main demand-main"><div className="domain-heading"><div><p>LOAD & DEMAND EXPERT</p><h2>15分钟需量预测与管控</h2></div><button type="button" onClick={() => onAsk(advicePrompt)}>询问需量专家</button></div>
      <section className="wide-chart demand-chart-panel"><div className="section-head"><div><p>AI FORECAST</p><h3>今日15分钟需量曲线</h3></div><span>{projection.dataBasis} · 悬浮查看数值</span></div><DemandForecastChart projection={projection} controlTargetKw={targetAvailable ? controlTargetKw : undefined} /><footer className="demand-model-meta"><span>{projection.methodLabel}</span><span>模型质量 <b>{projection.qualityGrade}</b></span><span>回测 MAE <b>{format(projection.validationMaeKw)} kW</b></span><span>预测峰值 <b>{projection.peakTime || "计算中"}</b></span></footer></section>
      <div className="domain-metrics demand-metrics">
        <MetricTile icon="D" label="当前15分钟需量" value={format(currentDemandKw)} unit="kW" note="时序功率按15分钟聚合" />
        <MetricTile icon="↗" label="预测最大需量" value={format(predictedMaxKw)} unit="kW" note={projection.methodLabel} tone={riskTime ? "amber" : "cyan"} />
        <MetricTile icon="◎" label="管控目标" value={targetAvailable ? format(controlTargetKw) : "—"} unit="kW" note="可在下方调整推演目标" tone="amber" />
        <MetricTile icon="△" label="预测剩余裕度" value={format(margin)} unit="kW" note={margin == null ? "等待目标或预测数据" : margin >= 0 ? "预测峰值低于管控目标" : "预测存在超限风险"} tone={margin != null && margin < 0 ? "amber" : "green"} />
      </div>
      <section className="demand-control-panel">
        <div className="demand-control-range">
          <header><span>管控目标推演</span><strong>{targetAvailable ? format(controlTargetKw, 0) : "—"} <small>kW</small></strong></header>
          <input
            type="range"
            min={sliderMin}
            max={sliderMax}
            step={sliderStep}
            value={targetAvailable ? Math.max(sliderMin, Math.min(sliderMax, controlTargetKw)) : sliderMin}
            aria-label="调整需量管控目标"
            onChange={event => setControlTargetKw(Number(event.target.value))}
          />
          <div><span>{sliderMin} kW</span><span>{sliderMax} kW</span></div>
        </div>
        <div className={`demand-control-status ${riskTime ? "warning" : ""}`}>
          <span>{riskTime ? "预计超限风险" : targetAvailable ? "预测处于目标内" : "管控目标待设置"}</span>
          <strong>{riskTime ? `${riskTime} 起` : margin != null ? `裕度 ${format(margin)} kW` : "数据计算中"}</strong>
          <small>模型质量 {projection.qualityGrade} · 每15分钟更新</small>
        </div>
        <div className="demand-control-action">
          <button type="button" onClick={() => onAsk(advicePrompt)}>生成管控建议</button>
          <p>仅用于预警与方案推演，不直接控制设备</p>
        </div>
      </section>
    </div><InsightList title="需量风险与建议" warnings={analysis?.warnings} empty={riskTime ? `短时预测显示 ${riskTime} 起可能超过当前管控目标，请核查生产计划。` : "当前短时预测未发现需量越限，建议持续监测。"} />
  </div>;
}

function QualityWorkspace({ analysis, onAsk }: { analysis: PowerAnalysisResult | null; onAsk: (prompt: string) => void }) {
  const quality = latestRecord(analysis?.metrics?.quality);
  const thdi = quality?.thdi ? Math.max(...Object.values(quality.thdi).map(item => item.max || 0)) : undefined;
  const thdu = quality?.thdu ? Math.max(...Object.values(quality.thdu).map(item => item.max || 0)) : undefined;
  return <div className="domain-workspace"><div className="domain-main"><div className="domain-heading"><div><p>POWER QUALITY EXPERT</p><h2>电能质量实时监测</h2></div><button onClick={() => onAsk("分析电能质量，重点说明功率因数、三相不平衡和THD证据")}>询问电力专家</button></div>
    <div className="domain-metrics"><MetricTile icon="φ" label="当前功率因数" value={format(quality?.power_factor?.latest, 3)} unit="" note={quality?.power_factor?.min != null ? `窗口最低 ${format(quality.power_factor.min, 3)}` : "暂无有效历史"} /><MetricTile icon="I" label="电流不平衡度" value={format(quality?.current_unbalance?.max, 2)} unit="%" note="异常需先核查CT和采样" tone="amber" /><MetricTile icon="Ui" label="最大 THDi" value={format(thdi, 2)} unit="%" note="平台阈值筛查" tone="amber" /><MetricTile icon="Uu" label="最大 THDu" value={format(thdu, 2)} unit="%" note="需结合PCC与适用标准" tone="green" /></div>
    <section className="quality-spectrum"><div className="section-head"><div><p>质量证据</p><h3>监测结果边界</h3></div><span>不由 LLM 重算</span></div><div className="evidence-grid"><article><strong>规则计算</strong><span>阈值、持续时间和最大值由 Python 工具生成</span></article><article><strong>现场核验</strong><span>不平衡与 THD 提醒不直接等同于标准超限</span></article><article><strong>人工审批</strong><span>任何补偿或治理动作必须进入审批流程</span></article></div></section>
  </div><InsightList title="电能质量异常" warnings={analysis?.warnings} empty="当前已执行的电能质量工具未产生平台级提醒。" /></div>;
}

function CompressorWorkspace({ analysis, onAsk }: { analysis: CompressorAnalysisResult | null; onAsk: (prompt: string) => void }) {
  const device = latestRecord(analysis?.metrics?.devices);
  const realtime = latestRecord(analysis?.metrics?.realtime);
  const pressure = latestRecord(analysis?.metrics?.pressure);
  const specific = analysis?.metrics?.specific_power;
  return <div className="domain-workspace"><div className="domain-main"><div className="domain-heading"><div><p>COMPRESSED AIR EXPERT</p><h2>空压系统运行与优化</h2></div><button onClick={() => onAsk("分析空压系统加载卸载、压力、比功率和节能机会")}>询问空压专家</button></div>
    <div className="domain-metrics"><MetricTile icon="P" label="供气压力" value={format(realtime?.supply_pressure_mpa ?? pressure?.avg_mpa, 3)} unit="MPa" note={pressure?.p95_p5_mpa != null ? `P95-P5 波动 ${format(pressure.p95_p5_mpa, 3)} MPa` : "压力历史计算中"} /><MetricTile icon="L" label="加载率" value={format(device?.load_rate_pct, 2)} unit="%" note={device?.unload_rate_pct != null ? `卸载率 ${format(device.unload_rate_pct, 2)}%` : "状态数据不足"} tone="green" /><MetricTile icon="E" label="系统比功率" value={format(specific?.average_kw_per_m3_min, 3)} unit="kW/(m³/min)" note="功率与流量时间对齐" /><MetricTile icon="T" label="排气温度" value={format(realtime?.discharge_temperature_c, 1)} unit="°C" note={realtime?.loaded == null ? "负载状态待获取" : realtime.loaded ? "当前加载运行" : "当前卸载运行"} tone="amber" /></div>
    <section className="compressor-flow"><div className="air-machine"><i>1#</i><strong>{realtime?.running ? "运行" : realtime?.running === false ? "停机" : "未知"}</strong><span>{format(device?.load_rate_pct, 1)}% 加载率</span></div><div className="air-line"><i /><i /><i /><i /><i /></div><div className="air-tank"><span>储气</span></div><div className="air-header"><strong>供气母管</strong><span>{format(realtime?.supply_pressure_mpa, 3)} MPa</span></div></section>
  </div><InsightList title="空压异常与节能筛查" warnings={analysis?.warnings} empty="当前已执行的空压工具未产生异常提醒；结论仅覆盖已执行能力。" /></div>;
}

function CarbonWorkspace({ summary, onAsk }: { summary?: DailySummary; onAsk: (prompt: string) => void }) {
  return <div className="domain-workspace"><div className="domain-main"><div className="domain-heading"><div><p>CARBON DATA READINESS</p><h2>碳减排数据准备</h2></div><button onClick={() => onAsk("当前项目是否具备计算碳排放和减排量的数据条件？")}>询问 AI</button></div>
    <section className="carbon-empty"><i>CO₂</i><div><h3>尚未接入可审计的碳排因子与产量基线</h3><p>当前平台可以提供电量、空压节能筛查与每日摘要，但不能把这些数据直接换算成正式碳排放或减排量。接入电网排放因子、核算边界、产量和基准期后，才能形成可核验结果。</p></div></section>
    {summary && <section className="latest-brief"><div className="section-head"><div><p>最近摘要</p><h3>{summary.title}</h3></div><span>{summary.summary_date}</span></div><Markdown text={summary.content} /></section>}
  </div><InsightList title="碳核算缺口" warnings={[{ severity: "medium", message: "碳排因子、组织边界、产量基线和核算标准尚未形成统一数据契约。" }]} empty="" /></div>;
}

function EventsWorkspace({ snapshots, onAsk }: { snapshots: DeviceSnapshot[]; onAsk: (prompt: string) => void }) {
  const events = snapshots.flatMap(snapshot => snapshot.alarms.map(alarm => ({ ...alarm, deviceName: snapshot.device.name })));
  return <div className="events-workspace"><div className="domain-heading"><div><p>INTELLIGENT EVENT LOOP</p><h2>智能事件与证据</h2></div><button onClick={() => onAsk("解释当前活动告警，并按优先级给出处置建议")}>询问事件专家</button></div>
    <div className="event-stats"><MetricTile icon="AI" label="今日发现事件" value={String(events.length)} unit="项" note="来自统一告警接口" /><MetricTile icon="!" label="高优先级" value={String(events.filter(event => ["CRITICAL", "MAJOR"].includes(event.severity)).length)} unit="项" note="需人工确认" tone="amber" /><MetricTile icon="✓" label="数据设备" value={String(snapshots.length)} unit="台" note="当前分析范围" tone="green" /></div>
    <section className="event-list"><div className="section-head"><div><p>实时事件流</p><h3>设备告警证据</h3></div><span>{events.length} 项</span></div>{events.length ? events.map((event, index) => <article key={`${event.created_time}-${index}`}><i>{event.severity.slice(0, 1)}</i><div><strong>{event.type}</strong><span>{event.deviceName} · {event.status}</span></div><time>{new Date(event.created_time).toLocaleString("zh-CN")}</time></article>) : <div className="chart-empty">当前设备范围没有活动告警</div>}</section>
  </div>;
}

const workspaceLabels: Record<Workspace, string> = {
  overview: "能源总览", demand: "需量管理", quality: "电能质量",
  compressor: "空压系统", carbon: "碳减排", events: "智能事件",
};

const assistantSuggestions: Record<Workspace, Array<{ tag: string; text: string }>> = {
  overview: [
    { tag: "运行概览", text: "概括当前能源运行情况，只回答关键指标和异常" },
    { tag: "需量风险", text: "当前是否存在需量超限风险？" },
    { tag: "异常定位", text: "今天有哪些用能异常需要关注？" },
    { tag: "设备状态", text: "哪些设备当前需要优先关注？" },
  ],
  demand: [
    { tag: "需量风险", text: "分析当前15分钟最大需量和需量控制目标风险" },
    { tag: "峰均比", text: "当前负荷峰均比是否异常？" },
    { tag: "峰值", text: "过去24小时负荷峰值发生在什么时候？" },
    { tag: "依据", text: "解释需量判断使用的数据口径" },
  ],
  quality: [
    { tag: "综合判断", text: "当前谐波与功率因数是否正常？" },
    { tag: "功率因数", text: "分析当前功率因数及历史最低值" },
    { tag: "三相不平衡", text: "当前三相电流不平衡是否需要关注？" },
    { tag: "谐波", text: "说明当前THD监测结果与依据" },
  ],
  compressor: [
    { tag: "运行效率", text: "空压系统今天是否存在低效运行？" },
    { tag: "加载卸载", text: "分析空压机加载率和卸载率" },
    { tag: "压力", text: "供气压力波动是否异常？" },
    { tag: "节能", text: "筛查当前空压系统节能机会" },
  ],
  carbon: [
    { tag: "数据条件", text: "当前是否具备计算碳排放的数据条件？" },
    { tag: "核算边界", text: "碳核算还缺少哪些基础数据？" },
    { tag: "能耗依据", text: "总结当前可用于碳核算的能源数据" },
    { tag: "口径", text: "正式计算减排量需要哪些口径？" },
  ],
  events: [
    { tag: "异常定位", text: "今天有哪些用能异常需要关注？" },
    { tag: "优先级", text: "按优先级解释当前活动告警" },
    { tag: "影响", text: "当前告警可能影响哪些设备？" },
    { tag: "依据", text: "展开当前异常的监测依据" },
  ],
};

function devicesForWorkspace(devices: Device[], workspace: Workspace) {
  if (workspace === "compressor") return devices.filter(device => device.type === "compressor");
  if (workspace === "demand" || workspace === "quality") return devices.filter(device => device.type === "meter");
  return devices.filter(device => ["ems", "meter", "compressor"].includes(device.type));
}

function friendlyDeviceName(device: Device, devices: Device[]) {
  const sameType = devices.filter(item => item.type === device.type);
  const ordinal = Math.max(1, sameType.findIndex(item => item.id.id === device.id.id) + 1);
  const category = device.type === "compressor" ? `${ordinal}号空压机`
    : device.type === "meter" ? `${ordinal}号电表`
      : device.type === "ems" ? "能源总表" : "工业设备";
  return `${category}（${device.name}）`;
}

function defaultContextDevice(workspace: Workspace, devices: Device[]) {
  const scoped = devicesForWorkspace(devices, workspace);
  if (["compressor", "demand", "quality"].includes(workspace) && scoped.length) return scoped[0].id.id;
  return "all";
}

function displayMessageTime(value?: string) {
  const date = value ? new Date(value) : new Date();
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function Assistant({ token, factoryId, devices, open, prompt, workspace, onOpenChange }: { token: string; factoryId: string; devices: Device[]; open: boolean; prompt: string; workspace: Workspace; onOpenChange: (open: boolean) => void }) {
  const [threadId] = useState(loadAssistantThreadId);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<AssistantMessage[]>(loadAssistantMessages);
  const [tools, setTools] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("理解问题");
  const [lastQuestion, setLastQuestion] = useState("");
  const [copiedId, setCopiedId] = useState("");
  const [feedback, setFeedback] = useState<Record<string, "up" | "down">>({});
  const [feedbackDraft, setFeedbackDraft] = useState<{ messageId: string; reasons: ChatFeedbackReason[]; comment: string } | null>(null);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackError, setFeedbackError] = useState("");
  const [evidenceOpen, setEvidenceOpen] = useState<Record<string, boolean>>({});
  const [contextOpen, setContextOpen] = useState(false);
  const [timeScope, setTimeScope] = useState<ContextTimeScope>("last_24h");
  const [selectedDeviceId, setSelectedDeviceId] = useState(() => defaultContextDevice(workspace, devices));
  const [composerExpanded, setComposerExpanded] = useState(false);
  const [showLatest, setShowLatest] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const autoFollowRef = useRef(true);
  const suggestions = assistantSuggestions[workspace];
  const scopedDevices = useMemo(() => devicesForWorkspace(devices, workspace), [devices, workspace]);
  const scopedDeviceKey = scopedDevices.map(device => device.id.id).join(",");
  const selectedDevice = scopedDevices.find(device => device.id.id === selectedDeviceId);
  const effectiveDeviceIds = selectedDeviceId === "all"
    ? scopedDevices.map(device => device.id.id)
    : selectedDevice ? [selectedDevice.id.id] : [];
  const contextDeviceLabel = selectedDevice
    ? friendlyDeviceName(selectedDevice, devices)
    : `全部当前页面设备（${scopedDevices.length}台）`;

  useEffect(() => { if (prompt) setInput(prompt.slice(0, 500)); }, [prompt]);
  useEffect(() => { if (open) window.setTimeout(() => inputRef.current?.focus(), 80); }, [open]);
  useEffect(() => {
    setSelectedDeviceId(defaultContextDevice(workspace, devices));
    setContextOpen(false);
  }, [workspace, scopedDeviceKey]);
  useEffect(() => {
    sessionStorage.setItem(ASSISTANT_MESSAGES_KEY, JSON.stringify(messages.slice(-40)));
  }, [messages]);
  useEffect(() => () => controllerRef.current?.abort(), []);
  useEffect(() => {
    if (!open || !autoFollowRef.current) return;
    window.requestAnimationFrame(() => {
      const element = messagesRef.current;
      if (element) element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    });
  }, [messages, busy, open]);

  function close() {
    if (busy) controllerRef.current?.abort();
    onOpenChange(false);
  }

  function stopGeneration() {
    controllerRef.current?.abort();
    setBusy(false);
    setMessages(current => current.map(message => message.id === "streaming" ? { ...message, id: crypto.randomUUID(), stopped: true, text: message.text || "生成已停止。" } : message));
  }

  async function submit(questionValue: string) {
    const question = questionValue.trim();
    if (!question || busy || question.length > 500) return;
    const controller = new AbortController();
    const requestId = crypto.randomUUID();
    const createdAt = new Date().toISOString();
    controllerRef.current = controller;
    setInput(""); setTools([]); setBusy(true); setProgress("理解问题"); setLastQuestion(question);
    autoFollowRef.current = true;
    setShowLatest(false);
    setMessages(current => [...current, { id: crypto.randomUUID(), who: "you", text: question, createdAt }, { id: "streaming", who: "ai", text: "", createdAt, requestId }]);
    let answer = "";
    let hasError = false;
    let answerMeta: CustomerAnswerMeta | undefined;
    const answerTools: string[] = [];
    try {
      await streamChat(token, {
        request_id: requestId, thread_id: threadId, message: question,
        device_scope: effectiveDeviceIds,
        page_context: { factory_id: factoryId, selected_device_ids: effectiveDeviceIds, workspace, time_scope: timeScope },
      }, (event: ChatStreamEvent) => {
        if (event.event === "node") setProgress("查询指标");
        if (event.event === "tool") {
          setProgress("查询指标");
          const name = String(event.content?.tool_name || "");
          const label = toolLabels[name] || name;
          if (label && !answerTools.includes(label)) answerTools.push(label);
          if (label) setTools([...answerTools]);
        }
        if (event.event === "message") {
          setProgress("组织答案");
          answer = String(event.content?.message || "");
          answerMeta = event.content?.answer_meta as CustomerAnswerMeta | undefined;
          setMessages(current => current.map(message => message.id === "streaming" ? { ...message, text: answer, meta: answerMeta, tools: [...answerTools] } : message));
        }
        if (event.event === "error") {
          hasError = true;
          answer = String(event.content?.message || "AI 服务暂时不可用");
        }
      }, controller.signal);
      setMessages(current => current.map(message => message.id === "streaming" ? { ...message, id: crypto.randomUUID(), requestId, meta: answerMeta, tools: [...answerTools], text: answer || "分析完成，但没有返回可展示内容。", errorCode: hasError ? "AI-504" : undefined } : message));
    } catch (reason) {
      if (controller.signal.aborted) return;
      const offline = typeof navigator !== "undefined" && !navigator.onLine;
      setMessages(current => current.map(message => message.id === "streaming" ? {
        ...message, id: crypto.randomUUID(), errorCode: offline ? "NET-OFFLINE" : "AI-504",
        text: offline ? "网络已断开，问题尚未完成。请恢复连接后重试。" : "AI 服务暂时无法生成答案。你的问题已保留，可稍后重试。",
      } : message));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      controllerRef.current = null;
    }
  }

  function send(event: FormEvent) { event.preventDefault(); void submit(input); }
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(input); }
    if (event.key === "Escape") close();
  }
  async function copyAnswer(message: AssistantMessage) {
    await navigator.clipboard.writeText(message.text);
    setCopiedId(message.id); window.setTimeout(() => setCopiedId(""), 1500);
  }
  function handleMessagesScroll() {
    const element = messagesRef.current;
    if (!element) return;
    const away = element.scrollHeight - element.scrollTop - element.clientHeight > 90;
    autoFollowRef.current = !away;
    setShowLatest(away);
  }
  function scrollToLatest() {
    const element = messagesRef.current;
    if (!element) return;
    autoFollowRef.current = true;
    setShowLatest(false);
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  }
  async function recordHelpful(message: AssistantMessage) {
    if (!message.requestId || feedbackBusy) return;
    setFeedbackBusy(true); setFeedbackError("");
    try {
      await sendChatFeedback(token, {
        request_id: message.requestId,
        thread_id: threadId,
        message_id: message.id,
        rating: "helpful",
        reasons: [],
        comment: "",
      });
      setFeedback(current => ({ ...current, [message.id]: "up" }));
      setFeedbackDraft(null);
    } catch {
      setFeedbackError("反馈提交失败，请稍后重试。");
    } finally {
      setFeedbackBusy(false);
    }
  }
  function toggleFeedbackReason(reason: ChatFeedbackReason) {
    setFeedbackDraft(current => current ? {
      ...current,
      reasons: current.reasons.includes(reason)
        ? current.reasons.filter(item => item !== reason)
        : [...current.reasons, reason],
    } : current);
  }
  async function submitImprovement(message: AssistantMessage) {
    if (!message.requestId || !feedbackDraft?.reasons.length || feedbackBusy) return;
    setFeedbackBusy(true); setFeedbackError("");
    try {
      await sendChatFeedback(token, {
        request_id: message.requestId,
        thread_id: threadId,
        message_id: message.id,
        rating: "needs_improvement",
        reasons: feedbackDraft.reasons,
        comment: feedbackDraft.comment.trim(),
      });
      setFeedback(current => ({ ...current, [message.id]: "down" }));
      setFeedbackDraft(null);
    } catch {
      setFeedbackError("反馈提交失败，请稍后重试。");
    } finally {
      setFeedbackBusy(false);
    }
  }

  return <>
    <button className={`assistant-fab ${open ? "active" : ""}`} onClick={() => open ? close() : onOpenChange(true)} aria-label={open ? "关闭 AI 助手" : "打开 AI 助手"}><i>AI</i><span>AI 助手</span><b>{open ? "×" : ">"}</b></button>
    {open && <div className="assistant-overlay" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
      <section className="assistant-drawer" role="dialog" aria-modal="true" aria-labelledby="assistant-title">
        <header><div><span><strong id="assistant-title">Aethra AI 助手</strong><button type="button" className="assistant-context-summary" onClick={() => setContextOpen(value => !value)} aria-expanded={contextOpen}><i />当前工厂 / {workspaceLabels[workspace]} / {contextDeviceLabel}<b>⌄</b></button><small>时间范围：{timeScopeLabels[timeScope]}</small></span></div><div className="assistant-window-actions"><button type="button" onClick={() => onOpenChange(false)} aria-label="最小化 AI 助手">−</button><button type="button" onClick={close} aria-label="关闭 AI 助手">×</button></div></header>
        {contextOpen && <section className="assistant-context-panel" aria-label="当前分析上下文"><label><span>分析对象</span><select value={selectedDeviceId} onChange={event => setSelectedDeviceId(event.target.value)}><option value="all">全部当前页面设备（{scopedDevices.length}台）</option>{scopedDevices.map(device => <option key={device.id.id} value={device.id.id}>{friendlyDeviceName(device, devices)}</option>)}</select></label><label><span>时间范围</span><select value={timeScope} onChange={event => setTimeScope(event.target.value as ContextTimeScope)}>{Object.entries(timeScopeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><p>设备与时间会随下一条问题发送；问题中明确写出的时间优先。</p></section>}
        <div className="assistant-messages" ref={messagesRef} onScroll={handleMessagesScroll}>
          {!messages.length && <div className="assistant-welcome"><i>AI</i><div><h3>你好，我是 Aethra</h3><p>我可以基于当前页面和已授权设备数据，回答能耗、需量、电能质量、空压及碳数据问题。</p></div></div>}
          {!messages.length && <div className="assistant-suggestions"><p>你可以这样问</p>{suggestions.map(item => <button type="button" key={item.text} onClick={() => void submit(item.text)}><span>{item.tag}</span><strong>{item.text}</strong><b aria-hidden="true">›</b></button>)}</div>}
          {messages.map(message => <article className={`assistant-message ${message.who} ${message.errorCode ? "error" : ""}`} key={message.id}>
            {message.errorCode ? <div className="assistant-error"><i>!</i><h3>暂时无法生成答案</h3><p>{message.text}</p><button type="button" onClick={() => void submit(lastQuestion)} disabled={busy}>重新生成</button><small>错误码：{message.errorCode}</small></div> : <>
              <div className="message-meta"><strong>{message.who === "ai" ? "Aethra AI" : "你"}</strong><time>{displayMessageTime(message.createdAt)}</time></div>
              {message.who === "ai" && <div className="assistant-answer-heading"><span>直接结论</span>{message.meta && <b className={message.meta.result_kind === "data_insufficient" ? "warning" : ""}>{resultKindLabels[message.meta.result_kind]}</b>}</div>}
              <Markdown text={message.text || "正在组织答案…"} />
              {message.meta?.expert_supplement_status === "unavailable" && <div className="assistant-notice">专家模型暂不可用，本回答保留确定性工具结果。</div>}
              {message.stopped && <div className="assistant-notice">已停止生成，已完成内容仍可查看。</div>}
              {message.who === "ai" && message.text && !message.stopped && <>
                <div className="message-actions">
                  <button type="button" onClick={() => void copyAnswer(message)}>{copiedId === message.id ? "已复制" : "复制"}</button>
                  {(message.meta || message.tools?.length) && <button type="button" className={evidenceOpen[message.id] ? "selected" : ""} onClick={() => setEvidenceOpen(current => ({ ...current, [message.id]: !current[message.id] }))}>▤ {evidenceOpen[message.id] ? "收起证据" : "查看证据"}</button>}
                  <button type="button" className={feedback[message.id] === "up" ? "selected" : ""} onClick={() => void recordHelpful(message)} disabled={feedbackBusy || !message.requestId} aria-label="回答有帮助">{feedback[message.id] === "up" ? "已反馈" : "有帮助"}</button>
                  <button type="button" className={feedback[message.id] === "down" ? "selected" : ""} onClick={() => { setFeedbackError(""); setFeedbackDraft({ messageId: message.id, reasons: [], comment: "" }); }} disabled={!message.requestId} aria-label="回答需改进">需改进</button>
                </div>
                {evidenceOpen[message.id] && <section className="assistant-answer-evidence"><header><strong>Evidence · 回答依据</strong>{message.meta && <span>{capabilityStateLabels[message.meta.capability_state]}</span>}</header>{message.meta?.evidence.map(item => <div key={item.label}><span>{item.label}</span><b>{item.value}</b></div>)}{message.meta?.data_cutoff_at && <div><span>数据截至</span><b>{new Date(message.meta.data_cutoff_at).toLocaleString("zh-CN")}{message.meta.updating ? "（仍在更新）" : ""}</b></div>}{message.meta && <div><span>数据质量</span><b>{message.meta.data_quality}</b></div>}{message.tools?.length ? <div><span>确定性工具</span><b>{message.tools.join("、")}</b></div> : null}</section>}
                {feedbackDraft?.messageId === message.id && <section className="assistant-feedback-panel"><strong>这条回答哪里需要改进？</strong><div>{(Object.keys(feedbackReasonLabels) as ChatFeedbackReason[]).map(reason => <button type="button" key={reason} className={feedbackDraft.reasons.includes(reason) ? "selected" : ""} onClick={() => toggleFeedbackReason(reason)}>{feedbackReasonLabels[reason]}</button>)}</div><textarea maxLength={500} value={feedbackDraft.comment} onChange={event => setFeedbackDraft(current => current ? { ...current, comment: event.target.value } : current)} placeholder="可补充说明（选填）" /><footer><button type="button" onClick={() => setFeedbackDraft(null)}>取消</button><button type="button" disabled={!feedbackDraft.reasons.length || feedbackBusy} onClick={() => void submitImprovement(message)}>提交反馈</button></footer>{feedbackError && <p>{feedbackError}</p>}</section>}
              </>}
            </>}
          </article>)}
          {busy && <div className="assistant-generation"><strong>正在生成答案</strong><ol><li className="done">理解问题</li><li className={progress !== "理解问题" ? "done" : "active"}>查询指标</li><li className={progress === "组织答案" ? "active" : ""}>组织答案</li></ol><button type="button" onClick={stopGeneration}>停止生成</button></div>}
          {!busy && messages.some(message => message.who === "ai" && !message.errorCode) && <div className="assistant-followups"><span>继续追问</span>{suggestions.slice(0, 3).map(item => <button type="button" key={item.text} onClick={() => void submit(item.text)}>{item.tag}</button>)}</div>}
        </div>
        {showLatest && <button type="button" className="assistant-back-latest" onClick={scrollToLatest}>↓ 回到最新消息</button>}
        <form className={`assistant-composer ${composerExpanded ? "expanded" : ""}`} onSubmit={send}><textarea ref={inputRef} value={input} maxLength={500} disabled={busy} onKeyDown={handleKeyDown} onChange={event => setInput(event.target.value.slice(0, 500))} placeholder={busy ? "当前状态不可提问" : "输入你的能碳问题"} aria-label="输入你的能碳问题" /><div><span className={input.length >= 480 ? "limit" : ""}>{input.length}/500</span><button type="button" onClick={() => setComposerExpanded(value => !value)}>{composerExpanded ? "收起输入框" : "展开输入框"}</button><small>Enter 发送 · Shift+Enter 换行</small></div><button disabled={busy || !input.trim()} aria-label="发送问题">↑</button></form>
      </section>
    </div>}
  </>;
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem("arthra_token") || "");
  const [user, setUser] = useState<User | null>(null);
  const [factories, setFactories] = useState<Factory[]>([]);
  const [factoryId, setFactoryId] = useState(() => sessionStorage.getItem("arthra_factory_id") || "");
  const [workspace, setWorkspace] = useState<Workspace>("overview");
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantPrompt, setAssistantPrompt] = useState("");
  const [clock, setClock] = useState(new Date());
  const data = useOperationsData(token, factoryId);
  useEffect(() => {
    if (!token) return;
    Promise.all([
      api<User>("/auth/me", token),
      api<Factory[]>("/factories", token),
    ]).then(([currentUser, availableFactories]) => {
      setUser(currentUser);
      setFactories(availableFactories);
      const selected = availableFactories.some(factory => factory.id === factoryId)
        ? factoryId
        : availableFactories[0]?.id || "";
      setFactoryId(selected);
      if (selected) sessionStorage.setItem("arthra_factory_id", selected);
    }).catch(() => {
      localStorage.removeItem("arthra_token");
      clearAssistantSession();
      setToken("");
    });
  }, [token, factoryId]);
  useEffect(() => { const timer = window.setInterval(() => setClock(new Date()), 30_000); return () => window.clearInterval(timer); }, []);
  const meter = data.snapshots.find(row => row.device.type === "meter");
  const latestSummary = data.summaries[0];
  function ask(prompt: string) { setAssistantPrompt(prompt); setAssistantOpen(true); }
  function login(value: string) {
    clearAssistantSession();
    localStorage.setItem("arthra_token", value);
    setToken(value);
  }
  function logout() {
    localStorage.removeItem("arthra_token");
    clearAssistantSession();
    sessionStorage.removeItem("arthra_factory_id");
    setToken("");
  }
  function selectFactory(nextFactoryId: string) {
    if (!nextFactoryId || nextFactoryId === factoryId) return;
    clearAssistantSession();
    sessionStorage.setItem("arthra_factory_id", nextFactoryId);
    setAssistantOpen(false);
    setFactoryId(nextFactoryId);
  }
  if (!token) return <Login onLogin={login} />;
  return <div className="control-room">
    <header className="topbar"><div className="vista-brand"><strong>AethraVista<sup>TM</sup></strong><span>AI 能碳运营管理平台</span></div><div className="top-status"><select aria-label="选择工厂" value={factoryId} onChange={event => selectFactory(event.target.value)}>{factories.map(factory => <option key={factory.id} value={factory.id}>{factory.name}</option>)}</select><span>{user?.role === "admin" ? "管理员" : "能源用户"}</span><time>数据更新 {clock.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time><i className={data.error ? "offline" : ""} /><button onClick={logout}>退出</button></div></header>
    {data.error && <div className="global-error">{data.error}</div>}
    <div className="dashboard-shell">
      <InsightRail workspace={workspace} summary={latestSummary} snapshots={data.snapshots} powerAnalysis={data.powerAnalysis} compressorAnalysis={data.compressorAnalysis} summaryBusy={data.summaryBusy} onRefresh={data.refreshSummary} onAsk={ask} />
      <main className="main-stage">
        {data.loading && !data.snapshots.length && <div className="stage-loading"><i /><span>正在连接统一工业数据服务</span></div>}
        {workspace === "overview" && <Overview snapshots={data.snapshots} powerAnalysis={data.powerAnalysis} compressorAnalysis={data.compressorAnalysis} loadForecast={data.demandForecast} />}
        {workspace === "demand" && <DemandWorkspace analysis={data.powerAnalysis} snapshot={meter} forecast={data.demandForecast} onAsk={ask} />}
        {workspace === "quality" && <QualityWorkspace analysis={data.powerAnalysis} onAsk={ask} />}
        {workspace === "compressor" && <CompressorWorkspace analysis={data.compressorAnalysis} onAsk={ask} />}
        {workspace === "carbon" && <CarbonWorkspace summary={latestSummary} onAsk={ask} />}
        {workspace === "events" && <EventsWorkspace snapshots={data.snapshots} onAsk={ask} />}
      </main>
    </div>
    <nav className="bottom-nav">{navItems.map(item => <button key={item.id} className={workspace === item.id ? "active" : ""} onClick={() => setWorkspace(item.id)}><i>{item.icon}</i><span>{item.label}</span></button>)}</nav>
    <Assistant key={factoryId} token={token} factoryId={factoryId} devices={data.devices} open={assistantOpen} prompt={assistantPrompt} workspace={workspace} onOpenChange={setAssistantOpen} />
  </div>;
}
