from __future__ import annotations

import logging
import sys
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent.parent

sys.path.insert(0, str(BACKEND_DIR))

from app.mcp.amap_http_server import mcp as amap_mcp
from app.mcp.weather_http_server import mcp as weather_mcp

logger = logging.getLogger(__name__)


def run_servers(host: str = "0.0.0.0", port: int = 8000):
    """运行 MCP HTTP 服务

    Args:
        host: 监听地址
        port: 监听端口
    """
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(f"启动 MCP HTTP 服务: {host}:{port}")
    logger.info("  - 高德地图服务: http://{host}:{port}/mcp/amap")
    logger.info("  - 天气服务: http://{host}:{port}/mcp/weather")

    from app.mcp.amap_http_server import mcp as amap
    from app.mcp.weather_http_server import mcp as weather

    amap.run(transport="streamable-http", host=host, port=port)
    weather.run(transport="streamable-http", host=host, port=port + 1)


if __name__ == "__main__":
    run_servers()
