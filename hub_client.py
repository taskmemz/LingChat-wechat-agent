from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional

import websockets

from config import AgentConfig
from models import Envelope, MessageType

logger = logging.getLogger("wechat-agent.hub")


class HubClient:
    def __init__(self, config: AgentConfig, node_id: str, node_type: str):
        self.config = config
        self.node_id = node_id
        self.node_type = node_type
        self.assigned_id: Optional[str] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._stop = False
        self._on_message: Optional[Callable] = None
        self._reconnect_count = 0

    def on_message(self, callback: Callable):
        self._on_message = callback

    async def connect(self, capabilities: list[dict] = None):
        while not self._stop:
            try:
                logger.info(f"Connecting to Hub at {self.config.hub_url} ...")
                self._ws = await websockets.connect(
                    self.config.hub_url, ping_interval=None
                )
                self._connected = True
                self._reconnect_count = 0
                logger.info("Connected to Hub")

                reg = Envelope(
                    type=MessageType.REGISTER,
                    from_node=self.node_id,
                    payload={
                        "node_type": self.node_type,
                        "node_id": self.node_id,
                        "capabilities": capabilities or [],
                        "version": "0.1.0",
                    },
                )
                await self._ws.send(json.dumps(reg.model_dump(by_alias=True)))
                ack_raw = await self._ws.recv()
                ack = Envelope(**json.loads(ack_raw))
                self.assigned_id = ack.to
                logger.info(f"Registered as {self.assigned_id}")

                await self._listen_loop()

            except (websockets.WebSocketException, asyncio.TimeoutError, OSError) as e:
                logger.warning(f"Connection error: {e}")
                if not self._stop:
                    await self._reconnect()

    async def _listen_loop(self):
        while not self._stop:
            try:
                raw = await self._ws.recv()
                data = json.loads(raw)
                envelope = Envelope(**data)

                if envelope.type == MessageType.PING:
                    pong = Envelope(
                        type=MessageType.PONG,
                        from_node=self.assigned_id or self.node_id,
                        to=envelope.from_node,
                    )
                    await self._ws.send(
                        json.dumps(pong.model_dump(by_alias=True))
                    )
                elif envelope.type == MessageType.REGISTER_ACK:
                    pass
                else:
                    if self._on_message:
                        await self._on_message(envelope)

            except websockets.WebSocketException:
                break
            except Exception as e:
                logger.error(f"Listen error: {e}", exc_info=True)
                break

        self._connected = False
        if not self._stop:
            await self._reconnect()

    async def _reconnect(self):
        delay = self.config.reconnect_delay
        self._reconnect_count += 1
        max_attempts = self.config.max_reconnect_attempts
        if max_attempts > 0 and self._reconnect_count > max_attempts:
            logger.error("Max reconnection attempts reached")
            return
        logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_count})")
        await asyncio.sleep(delay)

    async def send(self, envelope: Envelope):
        if not self._ws or not self._connected:
            logger.warning("Not connected to Hub")
            return
        try:
            await self._ws.send(json.dumps(envelope.model_dump(by_alias=True)))
        except Exception as e:
            logger.error(f"Send error: {e}")

    async def stop(self):
        self._stop = True
        if self._ws:
            await self._ws.close()
