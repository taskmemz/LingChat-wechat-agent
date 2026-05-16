from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("wechat-agent.authorizer")

TOOL_AUTHORIZATION: dict[str, str] = {
    "wechat_get_my_info": "auto",
    "wechat_get_friends": "auto",
    "wechat_get_friend_profile": "auto",
    "wechat_get_groups": "auto",
    "wechat_get_group_members": "auto",
    "wechat_get_common_groups": "auto",
    "wechat_post_moments": "auto",
    "wechat_get_moments": "auto",
    "wechat_get_chat_history": "auto",
    "wechat_send_message": "confirm",
    "wechat_send_messages": "confirm",
    "wechat_send_files": "confirm",
    "wechat_change_remark": "confirm",
    "wechat_delete_friend": "confirm",
    "wechat_add_friend": "confirm",
}


class AuthorizationResult:
    def __init__(self, approved: bool, reason: str = ""):
        self.approved = approved
        self.reason = reason


class Authorizer:
    def __init__(self, request_confirm_callback):
        self._request_confirm = request_confirm_callback

    async def authorize(
        self, tool_name: str, args: dict[str, Any], session_id: str
    ) -> AuthorizationResult:
        level = TOOL_AUTHORIZATION.get(tool_name, "confirm")

        if level == "auto":
            logger.info(f"Auto-approved: {tool_name}")
            return AuthorizationResult(True)

        if level == "confirm":
            logger.info(f"Requesting confirmation for: {tool_name}")
            description = self._describe_call(tool_name, args)
            approved = await self._request_confirm(session_id, description)
            if approved:
                return AuthorizationResult(True)
            return AuthorizationResult(False, "用户未确认")

        return AuthorizationResult(False, f"Unknown authorization level: {level}")

    def _describe_call(self, tool_name: str, args: dict[str, Any]) -> str:
        tool_descriptions = {
            "wechat_send_message": f"给「{args.get('target', '?')}」发送消息",
            "wechat_send_messages": f"给「{args.get('target', '?')}」发送多条消息",
            "wechat_send_files": f"给「{args.get('target', '?')}」发送文件",
            "wechat_change_remark": f"修改「{args.get('friend', '?')}」的备注为「{args.get('remark', '?')}」",
            "wechat_delete_friend": f"删除好友「{args.get('friend', '?')}」",
            "wechat_add_friend": f"添加好友（{args.get('number', '?')}）",
        }
        return tool_descriptions.get(tool_name, f"执行 {tool_name}")
