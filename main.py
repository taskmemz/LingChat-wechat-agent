from __future__ import annotations

import asyncio
import logging
import sys
import os
import uuid

# 最先设置：pyweixin 全局配置
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pyweixin.Config import GlobalConfig
GlobalConfig.close_weixin = False
GlobalConfig.load_delay = 1.0       # 默认 3.5s，降到 1s 加速
GlobalConfig.search_pages = 15      # 默认 5 页，加大避免掉到 emoji 搜索路径

from config import AgentConfig, CONFIG_FILE
from hub_client import HubClient
from authorizer import Authorizer
from tool_executor import ToolExecutor
from tool_registry import CAPABILITIES
from monitor_service import MonitorService
from models import Envelope, MessageType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wechat-agent")


def print_banner():
    print(
        r"""
  ╔══════════════════════════════════════╗
  ║     LingChat WeChat Agent v0.1       ║
  ╚══════════════════════════════════════╝
    """
    )


def get_hub_url() -> str:
    saved = AgentConfig.load()
    if saved:
        print(f"[?] Cloud Hub 地址 (上次: {saved.hub_url})")
        print(f"    直接回车使用默认或上次地址")
    else:
        print("[?] 请输入 Cloud Hub 地址")

    user_input = input("> ").strip()
    if not user_input and saved:
        return saved.hub_url
    if not user_input:
        return "ws://localhost:8766"
    return user_input


async def request_confirm(session_id: str, description: str) -> bool:
    logger.info(f"Authorization requested for {session_id}: {description}")

    def ask():
        print(f"\n[授权请求] {description}")
        print(f"    来自会话: {session_id}")
        reply = input("    回复「确认」允许: ").strip()
        return reply == "确认"

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, ask)


async def main():
    print_banner()

    config = AgentConfig.load()
    if not config:
        config = AgentConfig()

    hub_url = get_hub_url()
    config.hub_url = hub_url

    if config.hub_url == "ws://localhost:8766":
        print("[*] 使用默认地址 ws://localhost:8766")
    print(f"[*] Hub 地址: {config.hub_url}")

    config.save()
    print("[*] 配置已保存")

    node_id = f"pywechat-agent-{uuid.uuid4().hex[:8]}"
    hub = HubClient(config, node_id, "pywechat")
    authorizer = Authorizer(request_confirm)
    executor = ToolExecutor(hub, authorizer)
    monitor = MonitorService(config, hub)

    async def on_message(envelope: Envelope):
        if envelope.type == MessageType.TOOL_CALL:
            await executor.execute(envelope)
        elif envelope.type == MessageType.AI_REPLY:
            await executor.handle_ai_reply(envelope)
        elif envelope.type == MessageType.ERROR:
            logger.error(f"Error from Hub: {envelope.payload}")
        else:
            logger.debug(f"Unhandled message: {envelope.type}")

    hub.on_message(on_message)

    try:
        await asyncio.gather(
            hub.connect(capabilities=CAPABILITIES),
            _post_connection(monitor, hub),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await hub.stop()
        await monitor.stop()


async def _post_connection(monitor: MonitorService, hub: HubClient):
    while hub.assigned_id is None:
        await asyncio.sleep(1)

    print(f"[✓] 已注册为 {hub.assigned_id}")
    print(f"[✓] 已注册 {len(CAPABILITIES)} 个工具")
    print(f"[*] 开始监听微信消息...\n")

    await monitor.start()

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nBye!")
