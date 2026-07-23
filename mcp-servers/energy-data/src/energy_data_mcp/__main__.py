import json
import sys

from arthra.industrial_data.factory import get_industrial_data_service

from energy_data_mcp.server import EnergyDataMcpServer


def main() -> None:
    server = EnergyDataMcpServer(get_industrial_data_service())
    for line in sys.stdin:
        response = server.handle(json.loads(line))
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
