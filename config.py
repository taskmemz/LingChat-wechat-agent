from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

CONFIG_FILE = "config.json"


@dataclass
class AgentConfig:
    hub_url: str = "ws://localhost:8766"
    reconnect_delay: float = 3.0
    max_reconnect_attempts: int = 0  # 0 = unlimited
    monitor_interval: float = 2.0
    send_delay: float = 0.3
    listen_duration: str = "3s"
    log_level: str = "info"

    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "hub_url": self.hub_url,
                    "reconnect_delay": self.reconnect_delay,
                    "max_reconnect_attempts": self.max_reconnect_attempts,
                    "monitor_interval": self.monitor_interval,
                    "send_delay": self.send_delay,
                    "listen_duration": self.listen_duration,
                    "log_level": self.log_level,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

    @classmethod
    def load(cls) -> Optional[AgentConfig]:
        if not os.path.exists(CONFIG_FILE):
            return None
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = cls()
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
            return cfg
        except Exception:
            return None
