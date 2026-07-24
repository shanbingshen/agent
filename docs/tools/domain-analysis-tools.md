# 领域确定性工具说明

本文集中说明空压机、电力与需量工具、定向问答白名单和相关安全边界。所有数值由 Python 确定性计算，LLM 只解释已经校验的结果。

## 客户模式与管理员调试模式

Agent 对话默认使用客户模式。事实查询采用直接回答，例如“峰值 + 发生时间”或“周期电量 + 数据完整率”；只有综合分析才使用“一句话结论、核心指标、关键异常与证据、可执行建议”四层结构。

客户模式不展示基础模型名称、设备 UUID、原始点位字段、规则编码或小数形式的内部置信度；数据完整度和结论可信度使用高/中高/中/低表达。管理员可在 AI 分析页面显式开启调试模式，查看结构化分析、设备 ID、规则编号和模型版本，非管理员请求 `debug=true` 会被 API 拒绝。

## 定向问答与工具白名单

每条已登记问法都定义严格的 `intent / route / capabilities / max_tool_calls`。一次问答最多执行 4 个只读工具，不默认运行专家全部能力。

| 用户问题 | 专家 | 实际工具 |
| --- | --- | --- |
| 昨天什么时候用电负荷最高？ | 电力 | `detect_power_peaks` |
| 分析过去24小时的15分钟最大需量和峰均比 | 电力 | `calculate_rolling_15m_max_demand`、`analyze_peak_average_ratio` |
| 1号空压机昨天卸载严重吗？ | 空压 | `analyze_compressor_load_unload_rate` |
| 空压异常造成多少电费浪费？ | 空压 | `estimate_compressor_energy_saving`；没有电价时拒绝换算金额 |
| 你好 / 非工业问题 | 对话边界 | 不读取设备，不执行工具 |

时间表达会转换为带时区的查询窗口；“昨天”表示 `Asia/Shanghai` 的完整自然日。未指定时间时，回答会明确标注默认使用最近24小时。提到“3号电表/2号空压机”等具体对象但设备不存在或未在页面选中时，系统会追问，不会自动替换成相近设备。

需量越限唯一判定口径是 `meter_TotW` 的15分钟滚动平均与“需量控制目标”（内部字段 `declaredDemandKw`）的比较。实时功率或60秒桶峰值超过需量控制目标不等于计费需量已经越限；电表 `meter_MaxDmdSupW` 寄存器在统计周期未确认时不用于对话中的越限结论。

## 空压机十二项确定性工具

空压机 Agent 已注册以下只读工具。每个工具只激活一项 capability，数值由 Python 确定性计算，LLM 只负责解释结果。

| 工具 | capability | 主要输出 |
| --- | --- | --- |
| `analyze_compressor_load_unload_rate` | `load_rate` | 加载率、卸载率、运行/加载/卸载时长、覆盖率 |
| `detect_compressor_idle_running` | `idle_running` | 累计空载时间、最长连续空载时间；告警按最长连续时长判定 |
| `detect_compressor_frequent_starts` | `frequent_start` | 启动次数、有效观测小时数、每小时启动频率、频繁启停告警 |
| `analyze_compressor_pressure_fluctuation` | `pressure_fluctuation` | P5、P95、标准差、P95-P5 波动及告警 |
| `detect_compressor_high_supply_pressure` | `high_pressure` | 最大压力、超过上限的累计时间及告警 |
| `calculate_compressor_specific_power` | `specific_power` | 平均比功率、P95 比功率、功率/流量对齐样本数 |
| `get_compressor_realtime` | `realtime_status` | 运行/加载状态、压力、温度、关联功率和活动告警 |
| `get_compressor_energy` | `energy_consumption` | 关联电表累计读数差和周期用电量 |
| `analyze_compressor_group_control` | `group_control` | 多机加载顺序与群控筛查建议 |
| `detect_compressor_leakage` | `leakage` | 非生产时段平均流量和泄漏迹象 |
| `estimate_compressor_energy_saving` | `savings` | 卸载能耗和可优化电量筛查值 |
| `verify_compressor_optimization` | `verification` | 基线、措施时间和验证周期完备性 |

生产对话链路已接入 LangGraph `ToolNode`：Supervisor 给出的 capability 先经过服务端白名单校验，服务端生成工具调用，模型不能填写或修改设备 UUID。多个能力会先合并所需遥测 key、通过工业数据服务只构建一次 `CompressorSystemContext`，再通过 `InjectedState` 注入对应工具计算。

工具返回采用 `content_and_artifact`，收集节点只接受通过 Pydantic 校验的 `CompressorAnalysisResult`。最终文字由结构化事实、告警代码和有证据的建议确定性渲染，避免 LLM 新增阈值或缺失结论。

Chat SSE 会为每个完成的工具发送精简事件，不包含原始时序、ThingsBoard 凭据或请求头：

```text
event: tool
data: {"tool_name":"analyze_compressor_load_unload_rate","status":"success","capabilities":["load_rate"],"data_status":"available"}
```

直接调用综合分析 API：

```json
{
  "message": "分析单机加载率和卸载率",
  "device_scope": ["ThingsBoard-compressor-device-uuid"],
  "capabilities": ["load_rate"],
  "start_at": "2026-07-16T00:00:00+08:00",
  "end_at": "2026-07-17T00:00:00+08:00",
  "interval_seconds": 180
}
```

默认查询最近24小时并使用3分钟聚合桶。统一数据适配器负责遵守底层查询限制，领域上下文保持相同时间桶语义。输出包含数据覆盖率、设备关系、确定性指标、证据、缺失项和置信度，原始时序不会发送给 LLM。

## 电力需量与电能质量十三项确定性工具

电力专家使用 `apps/api/arthra/power` 中独立的数据上下文层和十三个 LangGraph 工具：

| 工具 | capability | 确定性输入/输出 |
| --- | --- | --- |
| `get_meter_realtime` | `realtime_power` | 最新 `meter_TotW` 和数据时间 |
| `get_energy_consumption` | `energy_consumption` | `meter_SupWh` 期末值减期初值 |
| `compare_energy_periods` | `energy_compare` | 相邻周期电量、变化量和变化率 |
| `calculate_rolling_15m_max_demand` | `demand_15m` | `meter_TotW`；15分钟滚动均值、最大值与窗口时间 |
| `detect_power_peaks` | `peak_detection` | `meter_TotW`；局部峰值与时间戳 |
| `analyze_peak_average_ratio` | `peak_average_ratio` | 瞬时峰值 / 窗口平均负荷 |
| `detect_declared_demand_exceedance` | `declared_demand_exceedance` | 滚动需量、`declaredDemandKw`；越限量、比例和持续时间 |
| `detect_voltage_deviation` | `voltage_deviation` | 三相线电压、额定电压；最大偏差与持续时间 |
| `detect_three_phase_imbalance` | `phase_imbalance` | `meter_ImbNgV/A`；电压/电流不平衡越限 |
| `detect_power_factor_anomaly` | `power_factor` | `meter_TotPF`；低功率因数持续时间 |
| `detect_thdu_thdi_anomaly` | `thd` | 三相 THDu/THDi；最大值与越限持续时间 |
| `analyze_3_5_7_harmonics` | `harmonics` | 三相3/5/7次电压和电流谐波；均值、最大值、主导次数 |
| `calculate_power_quality_abnormal_duration` | `abnormal_duration` | 上述质量指标；累计与最长连续异常时间 |

`POWER_*` 环境变量配置需量控制目标、额定电压和各项阈值。需量控制目标优先使用请求中的 `declared_demand_kw`，其次使用电表服务端属性 `declaredDemandKw`，最后使用 `POWER_DECLARED_DEMAND_KW`。

直接调用综合电力分析 API：

```json
POST /api/v1/power-analysis
{
  "message": "分析15分钟需量、电压偏差和THD异常",
  "device_scope": ["ThingsBoard-meter-device-uuid"],
  "interval_seconds": 60,
  "declared_demand_kw": 100,
  "capabilities": ["demand_15m", "declared_demand_exceedance", "voltage_deviation", "thd"]
}
```

生产对话会先由 Supervisor 路由至 `power`，再由服务端白名单选择工具。十三个工具共享一次构建的 `PowerSystemContext`，底层数据源凭据和原始时序不会进入 LLM 上下文；前端通过 SSE 只显示本次实际完成的工具。
