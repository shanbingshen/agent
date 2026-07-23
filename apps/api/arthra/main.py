"""兼容 ASGI 入口；实际应用由 arthra-gateway 工厂装配。"""

from arthra_gateway.app import create_app

app = create_app()
