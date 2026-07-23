import uuid
from pathlib import Path

from arthra.industrial_data.adapters.mock_file import MockFileIndustrialDataAdapter
from arthra.industrial_data.service import IndustrialDataService
from arthra_core import AgentPlugin
from arthra_mcp_client import LocalEnergyDataClient
from arthra_rag import KnowledgeFilters, RetrievalRequest
from arthra_rag.pipeline import ingest_markdown_file
from energy_data_mcp import EnergyDataMcpServer
from main_agent import MainAgent, build_graph
from power_agent import PowerAgent


def test_main_agent_keeps_compatible_graph_entrypoint():
    graph = MainAgent().build()
    assert graph is not None
    assert build_graph is not None


def test_power_plugin_declares_deterministic_tool_boundary():
    plugin = PowerAgent()
    assert isinstance(plugin, AgentPlugin)
    assert plugin.domain == "power"
    assert plugin.allowed_tools
    assert "PowerAnalysisService" in plugin.deterministic_service


def test_energy_data_mcp_restricts_device_scope_and_is_read_only():
    service = IndustrialDataService(MockFileIndustrialDataAdapter())
    server = EnergyDataMcpServer(service)
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response is not None
    assert all("control" not in tool["name"] for tool in response["result"]["tools"])

    allowed = server.handle({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "energy.latest_telemetry",
            "arguments": {"device_id": "mock-meter-01", "scope": {"allowed_device_ids": ["mock-meter-01"]}},
        },
    })
    assert allowed is not None and "result" in allowed

    denied = server.handle({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "energy.latest_telemetry",
            "arguments": {"device_id": "mock-meter-01", "scope": {"allowed_device_ids": []}},
        },
    })
    assert denied is not None and "error" in denied


def test_local_mcp_client_enforces_the_same_scope():
    client = LocalEnergyDataClient(
        IndustrialDataService(MockFileIndustrialDataAdapter()), {"mock-meter-01"}
    )
    assert client.latest_telemetry("mock-meter-01")
    try:
        client.latest_telemetry("mock-ems-01")
    except PermissionError:
        pass
    else:
        raise AssertionError("未授权设备不应被本地 MCP 回退客户端读取")


def test_rag_and_knowledge_assets_are_separated():
    root = Path(__file__).resolve().parents[1]
    assert (root / "knowledge/raw/shared").is_dir()
    assert (root / "knowledge/raw/compressor").is_dir()
    assert (root / "knowledge/processed/documents.jsonl").is_file()
    assert (root / "knowledge/manifests/ingestion.json").is_file()
    assert (root / "dataset/rag-eval").is_dir()
    assert (root / "packages/rag/src/arthra_rag/retriever").is_dir()
    assert (root / "packages/rag/src/arthra_rag/vectorstore").is_dir()
    assert not (root / "data").exists()
    assert not (root / "datasets").exists()
    assert not (root / "knowledge/equipment").exists()
    assert not (root / "knowledge/operation").exists()


def test_agent_knowledge_sources_are_explicit():
    root = Path(__file__).resolve().parents[1]
    compressor_config = (root / "agents/compressor-agent/config.yaml").read_text(encoding="utf-8")
    carbon_config = (root / "agents/carbon-agent/config.yaml").read_text(encoding="utf-8")
    assert "compressor" in compressor_config
    assert "carbon" not in compressor_config
    assert "carbon" in carbon_config
    assert "compressor" not in carbon_config


def test_rag_pipeline_keeps_legacy_ingestion_compatible(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("比功率是空压系统功率与供气流量的比值。", encoding="utf-8")
    chunks, embeddings = ingest_markdown_file(source)
    assert chunks
    assert len(chunks) == len(embeddings)


def test_rag_retrieval_contract_requires_scope():
    request = RetrievalRequest(
        query="GA75 E104 故障原因",
        filters=KnowledgeFilters(
            tenant_id=uuid.uuid4(),
            factory_id=uuid.uuid4(),
            knowledge_sources=["shared", "compressor"],
            device="compressor",
            model="GA75",
        ),
    )
    assert request.filters.knowledge_sources == ["shared", "compressor"]
