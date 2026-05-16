from __future__ import annotations

import asyncio
import logging
import time

from config import AgentConfig
from hub_client import HubClient
from models import Envelope, MessageType

logger = logging.getLogger("wechat-agent.monitor")


class MonitorService:
    def __init__(self, config: AgentConfig, hub: HubClient):
        self.config = config
        self.hub = hub
        self._running = False

    async def start(self):
        self._running = True
        logger.info("Monitor service started")
        asyncio.create_task(self._monitor_loop())

    async def stop(self):
        self._running = False

    async def _monitor_loop(self):
        while self._running:
            try:
                await self._check_new_messages()
            except Exception as e:
                logger.error(f"Monitor error: {e}", exc_info=True)
            await asyncio.sleep(self.config.monitor_interval)

    async def _check_new_messages(self):
        def scan():
            from pyweixin.utils import scan_for_new_messages

            try:
                result = scan_for_new_messages(close_weixin=False)
                return result
            except Exception as e:
                logger.error(f"Scan failed: {e}")
                return {}

        loop = asyncio.get_event_loop()
        new_messages = await loop.run_in_executor(None, scan)

        if new_messages:
            logger.info(f"New messages from: {list(new_messages.keys())}")

        for sender, count in new_messages.items():
            if count > 0:
                content = await self._read_messages(sender)
                if content:
                    envelope = Envelope(
                        type=MessageType.USER_MESSAGE,
                        from_node=self.hub.assigned_id or "",
                        payload={
                            "session_id": sender,
                            "user_id": sender,
                            "content": content,
                            "message_type": "text",
                        },
                    )
                    await self.hub.send(envelope)

    async def _read_messages(self, sender: str) -> str:
        def read():
            from pyweixin.WeChatTools import Navigator
            from pyweixin.WeChatAuto import Monitor

            try:
                dialog = Navigator.open_seperate_dialog_window(
                    friend=sender, window_minimize=True, close_weixin=False
                )
                result = Monitor.listen_on_chat(
                    dialog_window=dialog,
                    duration=self.config.listen_duration,
                    close_dialog_window=True,
                )
                texts = result.get("文本内容", [])
                senders = result.get("消息发送人", [])
                combined = []
                for t, s in zip(texts, senders):
                    if s and s != sender:
                        combined.append(f"{s}: {t}")
                    else:
                        combined.append(t)
                return "\n".join(combined) if combined else ""
            except Exception as e:
                logger.error(f"Read messages from {sender} failed: {e}")
                return ""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, read)
