from __future__ import annotations

import uuid
import time
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field


class MessageType(str, Enum):
    REGISTER = "register"
    REGISTER_ACK = "register_ack"
    PING = "ping"
    PONG = "pong"
    USER_MESSAGE = "user_message"
    AI_REPLY = "ai_reply"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_LIST = "tool_list"
    CONTEXT_SYNC = "context_sync"
    CONTEXT_REQUEST = "context_request"
    CONTEXT_RESPONSE = "context_response"
    CHANNEL_STATE = "channel_state"
    CONFIG = "config"
    ERROR = "error"


@dataclass
class Envelope:
    type: MessageType
    from_node: str
    to: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)

    def model_dump(self, by_alias: bool = False) -> dict:
        d = {
            "type": self.type.value if isinstance(self.type, Enum) else self.type,
            "from": self.from_node,
            "id": self.id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
        if self.to is not None:
            d["to"] = self.to
        return d


def envelope_from_dict(data: dict) -> Envelope:
    """Create Envelope from JSON dict, handling 'from' keyword conflict."""
    kwargs = dict(data)
    if "from" in kwargs:
        kwargs["from_node"] = kwargs.pop("from")
    return Envelope(**kwargs)
