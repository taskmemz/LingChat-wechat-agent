from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from authorizer import Authorizer, AuthorizationResult
from hub_client import HubClient
from message_splitter import split_message
from models import Envelope, MessageType
from wechat_lock import wechat_lock

logger = logging.getLogger("wechat-agent.executor")


class ToolExecutor:
    def __init__(self, hub: HubClient, authorizer: Authorizer):
        self.hub = hub
        self.authorizer = authorizer
        self._pyweixin_loaded = False
        self._executor = None
        self._loop = None
        self.monitor = None  # 由 main.py 设置
        self._temp_window = None  # 临时窗口引用

    def _ensure_pyweixin(self):
        if self._pyweixin_loaded:
            return
        # 关键：禁止 pyweixin 执行完自动关闭微信
        from pyweixin.Config import GlobalConfig
        GlobalConfig.close_weixin = False
        self._pyweixin_loaded = True

    async def execute(self, envelope: Envelope) -> None:
        tool_call_id = envelope.payload.get("tool_call_id", "")
        tool_name = envelope.payload.get("tool_name", "")
        arguments = envelope.payload.get("arguments", {})
        session_id = envelope.payload.get("session_id", "")

        logger.info(f"Executing: {tool_name}({arguments})")

        auth: AuthorizationResult = await self.authorizer.authorize(
            tool_name, arguments, session_id
        )

        if not auth.approved:
            logger.info(f"Execution rejected: {auth.reason}")
            result = Envelope(
                type=MessageType.TOOL_RESULT,
                from_node=self.hub.assigned_id or "",
                to=envelope.from_node,
                payload={
                    "tool_call_id": tool_call_id,
                    "success": False,
                    "error": auth.reason,
                    "session_id": session_id,
                },
            )
            await self.hub.send(result)
            return

        try:
            response = await self._execute_tool(tool_name, arguments)
            result = Envelope(
                type=MessageType.TOOL_RESULT,
                from_node=self.hub.assigned_id or "",
                to=envelope.from_node,
                payload={
                    "tool_call_id": tool_call_id,
                    "success": True,
                    "result": response,
                    "session_id": session_id,
                },
            )
            await self.hub.send(result)
        except Exception as e:
            logger.error(f"Tool execution failed: {e}", exc_info=True)
            result = Envelope(
                type=MessageType.TOOL_RESULT,
                from_node=self.hub.assigned_id or "",
                to=envelope.from_node,
                payload={
                    "tool_call_id": tool_call_id,
                    "success": False,
                    "error": str(e),
                    "session_id": session_id,
                },
            )
            await self.hub.send(result)

    async def send_text_to_wechat(
        self, session_id: str, target: str, content: str
    ) -> dict:
        self._ensure_pyweixin()
        parts = split_message(content)
        sent_count = 0
        for part in parts:

            def send(target=target, part=part):
                with wechat_lock:
                    try:
                        self._do_send_message(target, part)
                        logger.info(f"Sent msg to WeChat [{target[:20]}]")
                    except Exception as e:
                        logger.error(f"send_message to [{target[:20]}] failed: {e}")

            await self._run_sync(send)
            sent_count += 1
            if len(parts) > 1:
                await asyncio.sleep(0.5)

        # 通知监听器刷新快照，避免把 AI 回复当作新消息转发
        if self.monitor and session_id:
            await self.monitor.reset_snapshot(session_id)

        return {"sent": sent_count, "parts": parts}

    async def handle_ai_reply(self, envelope: Envelope) -> None:
        payload = envelope.payload
        session_id = payload.get("session_id", "")
        content = payload.get("content", "")
        segments = payload.get("segments", [])

        text_to_send = content or "\n".join(segments) if segments else ""
        if not text_to_send:
            return

        target = session_id
        try:
            await self.send_text_to_wechat(session_id, target, text_to_send)
            logger.info(f"Sent AI reply to WeChat [{session_id}]")
        except Exception as e:
            logger.error(f"Failed to send AI reply to WeChat [{session_id}]: {e}")

    async def _execute_tool(self, tool_name: str, args: dict) -> Any:
        self._ensure_pyweixin()

        handler_map = {
            "wechat_send_message": self._tool_send_message,
            "wechat_send_messages": self._tool_send_messages,
            "wechat_send_files": self._tool_send_files,
            "wechat_get_my_info": self._tool_get_my_info,
            "wechat_get_friends": self._tool_get_friends,
            "wechat_get_friend_profile": self._tool_get_friend_profile,
            "wechat_get_groups": self._tool_get_groups,
            "wechat_get_group_members": self._tool_get_group_members,
            "wechat_get_chat_history": self._tool_get_chat_history,
            "wechat_post_moments": self._tool_post_moments,
            "wechat_get_moments": self._tool_get_moments,
            "wechat_change_remark": self._tool_change_remark,
            "wechat_add_friend": self._tool_add_friend,
            "wechat_delete_friend": self._tool_delete_friend,
        }

        handler = handler_map.get(tool_name)
        if not handler:
            raise ValueError(f"Unknown tool: {tool_name}")

        def wrapped(args):
            with wechat_lock:
                return handler(args)

        return await self._run_sync(wrapped, args)

    async def _run_sync(self, func, *args, **kwargs):
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        return await self._loop.run_in_executor(self._executor, func, *args, **kwargs)

    # ========== Tool implementations ==========

    def _do_send_message(self, target: str, content: str):
        from pyweixin.utils import send_messages_to_friend

        # 优先复用监听器的独立窗口
        dialog = None
        close_after = False
        if self.monitor:
            dialog = self.monitor.get_window(target)
        if dialog is None:
            from pyweixin.WeChatTools import Navigator
            dialog = Navigator.open_seperate_dialog_window(
                friend=target, close_weixin=False,
            )
            close_after = True

        send_messages_to_friend(
            main_window=dialog,
            messages=[content],
            send_delay=0.3,
        )

        if close_after:
            try:
                dialog.close()
            except Exception:
                pass
        return True

    def _tool_send_message(self, args: dict) -> dict:
        target = args["target"]
        content = args["content"]
        parts = split_message(content)
        for part in parts:
            self._do_send_message(target, part)
            time.sleep(0.5)
        return {"sent": len(parts)}

    def _tool_send_messages(self, args: dict) -> dict:
        target = args["target"]
        messages = args["messages"]
        for msg in messages:
            self._do_send_message(target, msg)
            time.sleep(0.3)
        return {"sent": len(messages)}

    def _tool_send_files(self, args: dict) -> dict:
        from pyweixin.WeChatAuto import Files

        Files.send_files_to_friend(
            friend=args["target"], files=args["files"], send_delay=0.3
        )
        return {"status": "sent"}

    def _tool_get_my_info(self, args: dict) -> dict:
        from pyweixin.WeChatAuto import Contacts

        return Contacts.check_my_info()

    def _tool_get_friends(self, args: dict) -> list:
        from pyweixin.WeChatAuto import Contacts

        return Contacts.get_friends_detail()

    def _tool_get_friend_profile(self, args: dict) -> dict:
        from pyweixin.WeChatAuto import Contacts

        return Contacts.get_friend_profile(friend=args["friend"])

    def _tool_get_groups(self, args: dict) -> list:
        from pyweixin.WeChatAuto import Contacts

        return Contacts.get_groups_info()

    def _tool_get_group_members(self, args: dict) -> list:
        from pyweixin.WeChatAuto import Contacts

        return Contacts.get_groupMembers_info(group=args["group"])

    def _tool_get_chat_history(self, args: dict) -> list:
        from pyweixin.WeChatAuto import Messages

        result = Messages.dump_chat_history(
            friend=args["friend"], number=args["number"]
        )
        return result

    def _tool_post_moments(self, args: dict) -> dict:
        from pyweixin.WeChatAuto import Moments

        Moments.post_moments(
            text=args.get("text", ""), medias=args.get("medias", [])
        )
        return {"status": "posted"}

    def _tool_get_moments(self, args: dict) -> list:
        from pyweixin.WeChatAuto import Moments

        return Moments.dump_recent_posts(recent=args.get("recent", "Today"))

    def _tool_change_remark(self, args: dict) -> dict:
        from pyweixin.WeChatAuto import FriendSettings

        FriendSettings.change_remark(
            friend=args["friend"],
            remark=args["remark"],
            description=args.get("description"),
            phoneNum=args.get("phone"),
        )
        return {"status": "changed"}

    def _tool_add_friend(self, args: dict) -> dict:
        from pyweixin.WeChatAuto import FriendSettings

        FriendSettings.add_new_friend(
            number=args["number"],
            greetings=args.get("greetings"),
            remark=args.get("remark"),
        )
        return {"status": "request_sent"}

    def _tool_delete_friend(self, args: dict) -> dict:
        from pyweixin.WeChatAuto import FriendSettings

        FriendSettings.delete_friend(
            friend=args["friend"],
            clear_chat_history=1 if args.get("clear_chat", True) else 0,
        )
        return {"status": "deleted"}
