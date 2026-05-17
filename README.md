# LingChat WeChat Agent

Windows automation agent that bridges WeChat PC (v4.x) with the Cloud Hub. Detects new messages, reads conversation content, and sends AI replies back through WeChat.

## Requirements

- **Windows 10/11** only (uses pywinauto + UI Automation)
- **WeChat PC 4.x** (v4.1.6+)
- **Python 3.11+**
- WeChat must be **logged in** before starting the agent

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the agent
python main.py

# 3. Enter Cloud Hub address when prompted
Cloud Hub 地址: ws://192.168.2.109:8766/ws
```

The address is saved to `config.json` for subsequent runs.

## How It Works

```
1. Agent monitors WeChat session list for new messages
         ↓
2. Only opens windows for whitelisted contacts (configured on Hub)
         ↓
3. Reads recent messages via pywinauto automation
         ↓
4. Passes message text to Cloud Hub
         ↓
5. Receives AI reply from Hub
         ↓
6. Sends reply through WeChat (single contact or multiple windows)
```

## Configuration

All behavior is controlled by the Cloud Hub:

| Hub Setting | Effect |
|-------------|--------|
| `hub_config.json > whitelist` | Which contacts to respond to |
| `hub_config.json > batch_timeout` | Batch delay for message accumulation |

Non-whitelisted contacts are **completely ignored** (no windows opened, no messages read).

## File Structure

| File | Purpose |
|------|---------|
| `main.py` | Entry point, CLI interaction |
| `hub_client.py` | WebSocket client to Cloud Hub |
| `monitor_service.py` | WeChat message detection & reading |
| `tool_executor.py` | Tool execution (send messages, check contacts, etc.) |
| `tool_registry.py` | Available tool definitions |
| `authorizer.py` | Operation authorization |
| `message_splitter.py` | Message splitting for long replies |
| `wechat_lock.py` | Thread lock for serializing pywinauto operations |
| `pyweixin/` | Vendored pyweixin library (WeChat 4.0 automation) |

## Troubleshooting

### "WeChat not initialized"
- Make sure WeChat PC is running and logged in
- Restart the agent

### "open_separate TIMEOUT"
- The contact name might contain emoji or special characters
- Agent falls back to main-window reading for these cases

### Messages not detected
- Check that the contact is in `hub_config.json` whitelist
- Ensure the Cloud Hub is running and reachable
