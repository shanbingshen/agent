import { FormEvent, useEffect, useMemo, useState } from "react";
import { API_BASE, api, type ControlPlan, type DailySummary, type Device, type User } from "./api";

type View = "dashboard" | "daily" | "chat" | "knowledge" | "approvals" | "audit";
const views: Array<[View, string, string]> = [
  ["dashboard", "总览", "◫"], ["daily", "每日摘要", "☀"], ["chat", "AI 分析", "✦"], ["knowledge", "知识库", "◇"],
  ["approvals", "控制审批", "✓"], ["audit", "审计记录", "≡"],
];

function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [email, setEmail] = useState("admin@arthra.local");
  const [password, setPassword] = useState("Arthra@123456");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    const response = await fetch(`${API_BASE}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
    if (!response.ok) { setError("登录失败，请检查账号和密码"); return; }
    onLogin((await response.json()).access_token);
  }
  return <main className="login-shell">
    <div className="login-mark">A</div>
    <form className="login-card" onSubmit={submit}>
      <p className="eyebrow">ARTHRA PLATFORM</p><h1>AI 能碳大脑</h1>
      <p className="muted">连接数据、专家与设备，让每一次能源决策可解释、可审批、可追溯。</p>
      <label>邮箱<input value={email} onChange={e => setEmail(e.target.value)} /></label>
      <label>密码<input type="password" value={password} onChange={e => setPassword(e.target.value)} /></label>
      {error && <p className="error">{error}</p>}<button type="submit">进入控制台</button>
    </form>
  </main>;
}

function Dashboard({ devices }: { devices: Device[] }) {
  const cards = [
    ["实时功率", "375.8", "kW", "+2.4%"], ["今日用电", "4,218", "kWh", "-6.1%"],
    ["运行设备", String(devices.length || 3), "台", "正常"], ["待处理告警", "1", "条", "需关注"],
  ];
  return <section><div className="page-title"><div><p className="eyebrow">ENERGY OVERVIEW</p><h2>能源运行总览</h2></div><span className="live">● 实时更新</span></div>
    <div className="metrics">{cards.map(card => <article className="metric" key={card[0]}><span>{card[0]}</span><strong>{card[1]} <small>{card[2]}</small></strong><em>{card[3]}</em></article>)}</div>
    <div className="split"><article className="panel chart"><div className="panel-head"><h3>24 小时负荷趋势</h3><span>kW</span></div><div className="bars">{[45,52,48,63,57,70,67,78,65,72,61,55,68,74,81,76,69,62,58,66,73,64,52,47].map((h,i)=><i key={i} style={{height:`${h}%`}} />)}</div></article>
    <article className="panel"><div className="panel-head"><h3>设备状态</h3><span>{devices.length || 3} 台</span></div><div className="device-list">{(devices.length ? devices : [{id:{id:"1"},name:"Arthra-EMS-01",type:"ems"},{id:{id:"2"},name:"Arthra-Meter-01",type:"meter"},{id:{id:"3"},name:"Arthra-Compressor-01",type:"compressor"}]).map(d=><div className="device" key={d.id.id}><b>{d.name}</b><span>{d.type}</span><em>● 在线</em></div>)}</div></article></div>
  </section>;
}

function Chat({ token, devices }: { token: string; devices: Device[] }) {
  const [threadId] = useState(() => `web-${crypto.randomUUID()}`);
  const [input, setInput] = useState("分析当前能源运行状态并给出建议");
  const [messages, setMessages] = useState<Array<{who:string;text:string}>>([{who:"ai",text:"你好，我是 Arthra。可以让我分析 EMS、电力、空压机、趋势预警或生成能碳报告。"}]);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(()=>{setSelected(current=>current.length?current:devices.map(device=>device.id.id));},[devices]);
  function toggleDevice(id:string){setSelected(current=>current.includes(id)?current.filter(value=>value!==id):[...current,id]);}
  async function send(event: FormEvent) {
    event.preventDefault(); if (!input.trim() || busy) return;
    const question=input; setInput(""); setMessages(m=>[...m,{who:"you",text:question}]); setBusy(true);
    try {
      const response=await fetch(`${API_BASE}/chat`,{method:"POST",headers:{"Authorization":`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({thread_id:threadId,message:question,device_scope:selected})});
      if(!response.ok) throw new Error("对话请求失败");
      const reader=response.body!.getReader(); const decoder=new TextDecoder(); let buffer=""; let answer="";
      while(true){const {done,value}=await reader.read(); if(done)break; buffer+=decoder.decode(value,{stream:true}); const parts=buffer.split("\n\n"); buffer=parts.pop()||""; for(const part of parts){const line=part.split("\n").find(x=>x.startsWith("data: ")); if(!line)continue; const event=JSON.parse(line.slice(6)); if(event.event==="message") answer=event.content.message; if(event.event==="error") answer=event.content.message;}}
      setMessages(m=>[...m,{who:"ai",text:answer||"分析完成，但没有返回文本。"}]);
    } catch(error){setMessages(m=>[...m,{who:"ai",text:error instanceof Error?error.message:"请求失败"}]);} finally{setBusy(false);}
  }
  return <section className="chat-page"><div className="page-title"><div><p className="eyebrow">MULTI-AGENT WORKSPACE</p><h2>专家协同分析</h2></div></div><div className="device-picker"><div><b>分析设备范围</b><span>已选择 {selected.length} / {devices.length}</span></div><div className="device-chips">{devices.map(device=><button type="button" key={device.id.id} className={selected.includes(device.id.id)?"selected":""} onClick={()=>toggleDevice(device.id.id)}><i>{selected.includes(device.id.id)?"✓":"+"}</i><span>{device.name}<small>{device.type}</small></span></button>)}</div>{!devices.length&&<p>正在从 ThingsBoard 加载设备…</p>}</div><div className="chat-panel"><div className="messages">{messages.map((m,i)=><div className={`bubble ${m.who}`} key={i}><span>{m.who==="ai"?"A":"你"}</span><p>{m.text}</p></div>)}{busy&&<div className="thinking">Arthra 正在读取 ThingsBoard 数据并调用专家分析…</div>}</div><form className="composer" onSubmit={send}><textarea value={input} onChange={e=>setInput(e.target.value)} placeholder="询问能源运行、设备状态或节能建议…"/><button disabled={!selected.length||busy}>发送</button></form></div></section>;
}

function DailySummaries({ token, devices }: { token: string; devices: Device[] }) {
  const summaryDevices = useMemo(
    () => devices.filter(device => ["ems", "meter", "compressor"].includes(device.type)),
    [devices],
  );
  const [summaries, setSummaries] = useState<DailySummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [active, setActive] = useState<DailySummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setSelected(current => current.length ? current : summaryDevices.map(device => device.id.id));
  }, [summaryDevices]);
  const load = () => api<DailySummary[]>("/daily-summaries", token).then(rows => {
    setSummaries(rows); setActive(current => current || rows[0] || null);
  }).catch(reason => setError(reason instanceof Error ? reason.message : "摘要加载失败"));
  useEffect(() => { void load(); }, [token]);
  function toggleDevice(id: string) {
    setSelected(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  }
  async function generate() {
    if (!selected.length || busy) return;
    setBusy(true); setError("");
    try {
      const result = await api<DailySummary>("/daily-summaries/generate", token, {
        method: "POST", body: JSON.stringify({ device_scope: selected }),
      });
      setActive(result); setSummaries(current => [result, ...current.filter(item => item.id !== result.id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "摘要生成失败");
    } finally { setBusy(false); }
  }
  const overview = active?.statistics.overview;
  return <section className="daily-page">
    <div className="page-title"><div><p className="eyebrow">AI DAILY BRIEFING</p><h2>AI 每日摘要</h2></div><span className="live">每天自动生成 · 可手动刷新</span></div>
    <div className="device-picker"><div><b>摘要设备范围</b><span>已选择 {selected.length} / {summaryDevices.length}</span></div><div className="device-chips">{summaryDevices.map(device => <button type="button" key={device.id.id} className={selected.includes(device.id.id) ? "selected" : ""} onClick={() => toggleDevice(device.id.id)}><i>{selected.includes(device.id.id) ? "✓" : "+"}</i><span>{device.name}<small>{device.type}</small></span></button>)}</div></div>
    <div className="summary-actions"><button onClick={generate} disabled={!selected.length || busy}>{busy ? "正在汇总 ThingsBoard 数据并生成…" : "立即生成今日摘要"}</button><span>统计窗口：生成时刻向前 24 小时</span></div>
    {error && <p className="error">{error}</p>}
    {active && <>
      <div className="summary-metrics">
        <article><span>覆盖设备</span><b>{overview?.available_device_count ?? 0}/{overview?.device_count ?? 0}</b></article>
        <article><span>平均有功功率</span><b>{overview?.average_active_power_kw?.toFixed(1) ?? "--"}<small> kW</small></b></article>
        <article><span>窗口用电增量</span><b>{overview?.energy_consumption_kwh?.toFixed(1) ?? "--"}<small> kWh</small></b></article>
        <article><span>提醒 / 告警</span><b>{overview?.warning_count ?? 0}<small> / {overview?.alarm_count ?? 0}</small></b></article>
      </div>
      <div className="summary-layout"><article className="panel summary-report"><div className="panel-head"><div><h3>{active.title}</h3><small>{new Date(active.period_start).toLocaleString("zh-CN")} 至 {new Date(active.period_end).toLocaleString("zh-CN")}</small></div><span>{active.status} · {active.model_name}</span></div><pre>{active.content}</pre></article>
      <aside className="panel summary-history"><div className="panel-head"><h3>历史摘要</h3><span>{summaries.length}</span></div>{summaries.map(summary => <button key={summary.id} className={active.id === summary.id ? "active" : ""} onClick={() => setActive(summary)}><b>{summary.summary_date}</b><span>{summary.trigger === "scheduled" ? "自动" : "手动"} · {new Date(summary.created_at).toLocaleTimeString("zh-CN", {hour:"2-digit",minute:"2-digit"})}</span></button>)}</aside></div>
    </>}
    {!active && !busy && <div className="panel empty">尚无每日摘要，请选择设备后生成第一份摘要。</div>}
  </section>;
}

function Knowledge({ token }: { token: string }) {
  const [docs,setDocs]=useState<Array<{id:string;filename:string;status:string}>>([]); const [notice,setNotice]=useState("");
  const load=()=>api<typeof docs>("/knowledge/documents",token).then(setDocs).catch(e=>setNotice(e.message)); useEffect(()=>{void load();},[token]);
  async function upload(event:FormEvent<HTMLFormElement>){event.preventDefault();const input=event.currentTarget.elements.namedItem("file") as HTMLInputElement;if(!input.files?.[0])return;const body=new FormData();body.append("file",input.files[0]);await api("/knowledge/documents",token,{method:"POST",body});setNotice("文档已完成切分和向量化");load();}
  return <section><div className="page-title"><div><p className="eyebrow">KNOWLEDGE RESOURCE</p><h2>企业知识库</h2></div></div><div className="split"><form className="panel upload" onSubmit={upload}><h3>添加知识文档</h3><p className="muted">支持 UTF-8 TXT、Markdown 与 CSV，单文件不超过 5 MB。</p><input name="file" type="file" accept=".txt,.md,.csv"/><button>上传并处理</button>{notice&&<p>{notice}</p>}</form><article className="panel"><div className="panel-head"><h3>已入库文档</h3><span>{docs.length}</span></div>{docs.map(d=><div className="document" key={d.id}><b>{d.filename}</b><em>{d.status}</em></div>)}{!docs.length&&<p className="empty">尚未上传文档</p>}</article></div></section>;
}

function Approvals({ token, plans, reload }: { token:string;plans:ControlPlan[];reload:()=>void }) {
  async function action(id:string,verb:"approve"|"reject"){await api(`/control-plans/${id}/${verb}`,token,{method:"POST",body:verb==="reject"?JSON.stringify({reason:"审批员拒绝"}):undefined});reload();}
  return <section><div className="page-title"><div><p className="eyebrow">HUMAN IN THE LOOP</p><h2>设备控制审批</h2></div><span className="safety">AI 无法绕过此审批</span></div><div className="panel table-wrap"><table><thead><tr><th>设备</th><th>控制方法</th><th>参数</th><th>风险</th><th>状态</th><th>操作</th></tr></thead><tbody>{plans.map(p=><tr key={p.id}><td><b>{p.device_name}</b><small>{p.device_type}</small></td><td>{p.method}</td><td><code>{JSON.stringify(p.params)}</code></td><td>{p.risk_level}</td><td><span className={`status ${p.status}`}>{p.status}</span></td><td>{p.status==="proposed"&&<div className="actions"><button onClick={()=>action(p.id,"approve")}>批准执行</button><button className="ghost" onClick={()=>action(p.id,"reject")}>拒绝</button></div>}</td></tr>)}</tbody></table>{!plans.length&&<p className="empty">当前没有控制计划</p>}</div></section>;
}

function Audit({ token }: {token:string}) { const [events,setEvents]=useState<Array<{id:string;action:string;resource_id:string;created_at:string;details:unknown}>>([]); useEffect(()=>{api<typeof events>("/audit-events",token).then(setEvents).catch(()=>setEvents([]));},[token]); return <section><div className="page-title"><div><p className="eyebrow">AUDIT TRAIL</p><h2>不可变操作记录</h2></div></div><div className="panel timeline">{events.map(e=><div key={e.id}><i/><p><b>{e.action}</b><span>{new Date(e.created_at).toLocaleString("zh-CN")}</span></p><code>{e.resource_id}</code></div>)}{!events.length&&<p className="empty">暂无记录或当前角色无查看权限</p>}</div></section>; }

export default function App(){
  const [token,setToken]=useState(()=>localStorage.getItem("arthra_token")||""); const [user,setUser]=useState<User|null>(null); const [view,setView]=useState<View>("dashboard"); const [devices,setDevices]=useState<Device[]>([]); const [plans,setPlans]=useState<ControlPlan[]>([]);
  const reload=()=>{if(!token)return;api<{data:Device[]}>("/devices",token).then(r=>setDevices(r.data||[])).catch(()=>setDevices([]));api<ControlPlan[]>("/control-plans",token).then(setPlans).catch(()=>setPlans([]));};
  useEffect(()=>{if(!token)return;api<User>("/auth/me",token).then(setUser).catch(()=>{setToken("");localStorage.removeItem("arthra_token")});reload();},[token]);
  const pending=useMemo(()=>plans.filter(p=>p.status==="proposed").length,[plans]);
  function loggedIn(value:string){localStorage.setItem("arthra_token",value);setToken(value)} if(!token)return <Login onLogin={loggedIn}/>;
  return <div className="app"><aside><div className="brand"><b>A</b><div><strong>Arthra</strong><span>AI 能碳大脑</span></div></div><nav>{views.map(([id,label,icon])=><button key={id} className={view===id?"active":""} onClick={()=>setView(id)}><i>{icon}</i>{label}{id==="approvals"&&pending>0&&<em>{pending}</em>}</button>)}</nav><div className="profile"><span>{user?.email.slice(0,1).toUpperCase()}</span><div><b>{user?.email||"加载中"}</b><small>{user?.role}</small></div><button onClick={()=>{localStorage.clear();setToken("")}}>↗</button></div></aside><main className="content">{view==="dashboard"&&<Dashboard devices={devices}/>} {view==="daily"&&<DailySummaries token={token} devices={devices}/>} {view==="chat"&&<Chat token={token} devices={devices}/>} {view==="knowledge"&&<Knowledge token={token}/>} {view==="approvals"&&<Approvals token={token} plans={plans} reload={reload}/>} {view==="audit"&&<Audit token={token}/>}</main></div>;
}
