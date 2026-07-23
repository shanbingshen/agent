"""Arthra 首个只读 MCP Server 的最小 JSON-RPC 2.0 实现。

仅实现 MCP 初始化、tools 和 resources 所需子集；控制能力不在此 Server 中。
"""

from typing import Any

from arthra.contracts import StrictModel
from arthra.industrial_data import IndustrialDataService
from pydantic import Field


class McpScope(StrictModel):
    allowed_device_ids: list[str] = Field(default_factory=list, max_length=1000)


class EnergyDataMcpServer:
    protocol_version = "2025-06-18"

    def __init__(self, service: IndustrialDataService):
        self._service = service

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": "energy.list_devices", "description": "分页读取已授权设备", "inputSchema": {"type": "object"}},
            {"name": "energy.latest_telemetry", "description": "读取已授权设备最新遥测", "inputSchema": {"type": "object", "required": ["device_id"]}},
            {"name": "energy.telemetry_history", "description": "读取已授权设备历史时序", "inputSchema": {"type": "object", "required": ["device_id", "keys", "start_ts", "end_ts"]}},
            {"name": "energy.attributes", "description": "读取已授权设备属性", "inputSchema": {"type": "object", "required": ["device_id"]}},
            {"name": "energy.alarms", "description": "读取已授权设备告警", "inputSchema": {"type": "object", "required": ["device_id"]}},
        ]

    def list_resources(self) -> list[dict[str, str]]:
        return [{"uri": "arthra://energy/provider", "name": "当前工业数据提供方"}]

    def _scope(self, arguments: dict[str, Any]) -> McpScope:
        return McpScope.model_validate(arguments.pop("scope", {}))

    @staticmethod
    def _authorize(scope: McpScope, device_id: str) -> None:
        if device_id not in scope.allowed_device_ids:
            raise PermissionError("设备不在当前授权范围内")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> object:
        arguments = dict(arguments)
        scope = self._scope(arguments)
        if name == "energy.list_devices":
            page = self._service.list_devices(
                page=int(arguments.get("page", 0)), page_size=int(arguments.get("page_size", 100)),
                text_search=str(arguments.get("text_search", "")),
            )
            allowed = set(scope.allowed_device_ids)
            return page.model_copy(update={"data": [item for item in page.data if item.id.id in allowed]})
        device_id = str(arguments.pop("device_id"))
        self._authorize(scope, device_id)
        if name == "energy.latest_telemetry":
            return self._service.latest_telemetry(device_id, arguments.get("keys"))
        if name == "energy.telemetry_history":
            return self._service.telemetry_history(device_id, **arguments)
        if name == "energy.attributes":
            return self._service.attributes(device_id, arguments.get("keys"))
        if name == "energy.alarms":
            return self._service.list_alarms(device_id, **arguments)
        raise ValueError(f"未知 MCP 工具：{name}")

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        try:
            if method == "initialize":
                result: object = {"protocolVersion": self.protocol_version, "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "arthra-energy-data", "version": "0.1"}}
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "resources/list":
                result = {"resources": self.list_resources()}
            elif method == "resources/read":
                result = {"contents": [{"uri": "arthra://energy/provider", "text": self._service.provider_name}]}
            elif method == "tools/call":
                params = request.get("params", {})
                value = self.call_tool(params["name"], params.get("arguments", {}))
                serialized = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
                result = {"content": [{"type": "text", "text": str(serialized)}]}
            else:
                raise ValueError(f"不支持的 MCP 方法：{method}")
        except Exception as exc:
            if request_id is None:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
