import asyncio
import json
import websockets


async def test_agent_connection():
    uri = "ws://localhost:8766/ws"
    async with websockets.connect(uri) as ws:
        reg = {
            "type": "register",
            "from": "test-monitor",
            "payload": {
                "node_type": "lingchat",
                "node_id": "test-monitor",
                "capabilities": [],
            },
        }
        await ws.send(json.dumps(reg))
        ack_raw = await ws.recv()
        ack = json.loads(ack_raw)
        print(f"[test] Registered: {ack['payload']}")

        tool_list = await ws.recv()
        tl = json.loads(tool_list)
        caps = tl["payload"]["capabilities"]
        print(f"[test] Received tool list: {len(caps)} capabilities")
        assert len(caps) > 0, "No capabilities received"
        assert caps[0]["name"] == "wechat_send_message", "First tool mismatch"

        for cap in caps:
            print(f"  - {cap['name']} ({cap['authorization']})")

        tool_call = {
            "type": "tool_call",
            "from": "test-monitor",
            "to": tl["from"],
            "payload": {
                "tool_call_id": "test-call-1",
                "tool_name": "wechat_get_my_info",
                "arguments": {},
                "session_id": "test-session",
            },
        }
        await ws.send(json.dumps(tool_call))
        print("[test] Sent tool_call")

        result_raw = await ws.recv()
        result = json.loads(result_raw)
        print(f"[test] Got result: {result['payload']['success']}")

        error_call = {
            "type": "tool_call",
            "from": "test-monitor",
            "to": tl["from"],
            "payload": {
                "tool_call_id": "test-call-2",
                "tool_name": "wechat_send_message",
                "arguments": {"target": "测试好友", "content": "你好"},
                "session_id": "test-session",
            },
        }
        await ws.send(json.dumps(error_call))

        result2_raw = await ws.recv()
        result2 = json.loads(result2_raw)
        print(f"[test] Authorized result: {result2['payload']}")


asyncio.run(test_agent_connection())
