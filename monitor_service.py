from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from config import AgentConfig
from hub_client import HubClient
from models import Envelope, MessageType
from wechat_lock import wechat_lock

logger = logging.getLogger("wechat-agent.monitor")

_BACKOFF_SCHEDULE = [2, 5, 15, 30, 60]
_LOCK_TIMEOUT = 8  # lock 最多等 8s，拿不到就放弃


def _lock() -> bool:
    """尝试获取 wechat_lock，超时返回 False"""
    locked = wechat_lock.acquire(timeout=_LOCK_TIMEOUT)
    return locked


def _unlock():
    try:
        wechat_lock.release()
    except RuntimeError:
        pass


def _safe_call(fn, *args, **kwargs):
    """在 lock 保护下调用 fn，超时或异常都兜底"""
    if not _lock():
        logger.warning("wechat_lock timeout, skipping")
        return None
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(f"{fn.__name__} failed: {e}")
        return None
    finally:
        _unlock()


class MonitorService:
    def __init__(self, config: AgentConfig, hub: HubClient):
        self.config = config
        self.hub = hub
        self._running = False
        self._consecutive_errors = 0
        self._main_window: Any = None

    async def start(self):
        self._running = True
        loop = asyncio.get_event_loop()
        self._main_window = await loop.run_in_executor(None, self._init_weixin)
        logger.info(f"WeChat initialized: {self._main_window is not None}")
        asyncio.create_task(self._monitor_loop())
        logger.info("Monitor started")

    def _init_weixin(self):
        from pyweixin.WeChatTools import Navigator
        return _safe_call(Navigator.open_weixin, is_maximize=False)

    async def stop(self):
        self._running = False

    async def _monitor_loop(self):
        while self._running:
            try:
                if self._main_window is None:
                    logger.warning("WeChat not initialized")
                else:
                    await self._check_new_messages()
                    self._consecutive_errors = 0
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(f"Monitor err ({self._consecutive_errors}x): {e}")
            idx = min(self._consecutive_errors, len(_BACKOFF_SCHEDULE) - 1)
            await asyncio.sleep(_BACKOFF_SCHEDULE[idx])

    async def _check_new_messages(self):
        def scan(w):
            import time as _t
            from pyweixin.utils import scan_for_new_messages
            print("[TRACE] scan: waiting for lock...", flush=True)
            t0 = _t.time()
            if not _lock():
                logger.warning("scan: lock timeout")
                return {}
            print(f"[TRACE] scan: got lock after {_t.time()-t0:.1f}s", flush=True)
            try:
                result = scan_for_new_messages(main_window=w, close_weixin=False)
                print(f"[TRACE] scan: done in {_t.time()-t0:.1f}s, {len(result)} contacts", flush=True)
                return result
            except Exception as e:
                logger.error(f"Scan failed: {e}")
                return {}
            finally:
                _unlock()

        loop = asyncio.get_event_loop()
        new_messages = await loop.run_in_executor(None, scan, self._main_window)

        if new_messages:
            logger.info(f"New messages from: {list(new_messages.keys())}")

        for sender, count in new_messages.items():
            if count > 0:
                content = await self._read_messages(sender)
                if content:
                    await self._send_user_msg(sender, content)

    async def _send_user_msg(self, sender: str, content: str):
        await self.hub.send(
            Envelope(
                type=MessageType.USER_MESSAGE,
                from_node=self.hub.assigned_id or "",
                payload={
                    "session_id": sender,
                    "user_id": sender,
                    "content": content,
                    "message_type": "text",
                },
            )
        )

    async def _read_messages(self, sender: str) -> str:
        def read():
            return _click_and_read(self._main_window, sender)

        loop = asyncio.get_event_loop()
        task = loop.run_in_executor(None, read)
        try:
            return await asyncio.wait_for(task, timeout=15) or ""
        except asyncio.TimeoutError:
            logger.error(f"Read '{sender}' TIMEOUT 15s")
            return ""


def _click_and_read(main_window, sender: str) -> str:
    """找 → 点 → 读，每个 pywinauto 操作单独 lock"""
    import time as _t
    from pyweixin.Uielements import Lists, SideBar, Main_window, Texts

    def dbg(msg):
        print(f"[DBG] read: {msg}", flush=True)

    dbg("step1 set_focus")
    _safe_call(main_window.set_focus)

    dbg("step2 sidebar")
    if _lock():
        try:
            btn = main_window.child_window(**SideBar.Weixin)
            if btn.exists(timeout=0.5):
                btn.click_input()
        except Exception:
            pass
        finally:
            _unlock()

    dbg("step3 session_list")
    session_list = None
    if _lock():
        try:
            sl = main_window.child_window(**Main_window.SessionList)
            if sl.exists(timeout=1):
                session_list = sl
        finally:
            _unlock()
    if session_list is None:
        dbg("FAIL: session_list not found")
        return ""

    dbg("step4 find sender")
    target_item = None
    if _lock():
        try:
            items = session_list.children(control_type="ListItem")
            dbg(f"  session items: {len(items) if items else 0}")
            for idx, item in enumerate(items or []):
                try:
                    aid = item.automation_id().replace("session_item_", "")
                    if aid == sender:
                        target_item = item
                        dbg(f"  found '{sender}' at index {idx}")
                        break
                except Exception:
                    continue
        finally:
            _unlock()
    if target_item is None:
        dbg(f"FAIL: '{sender}' not found")
        return ""

    dbg("step5 click sender")
    if _lock():
        try:
            target_item.click_input()
        except Exception as e:
            dbg(f"FAIL click: {e}")
            return ""
        finally:
            _unlock()

    dbg("step6 wait for chat")
    _t.sleep(0.5)
    name_label = dict(Texts.CurrentChatNameText)
    name_label["title"] = sender
    chat_ok = False
    if _lock():
        try:
            chat_ok = main_window.child_window(**name_label).exists(timeout=2)
        finally:
            _unlock()
    if not chat_ok:
        dbg(f"FAIL: chat '{sender}' didn't open")
        return ""
    dbg("chat opened OK")

    dbg("step7 read texts")
    texts = []
    if _lock():
        try:
            area = main_window.child_window(**Lists.FriendChatList)
            if area.exists(timeout=2):
                dbg("chat area exists")
                # 遍历整个聊天区的全部 Text 控件（不限 types）
                for ctrl in area.descendants():
                    try:
                        t = ctrl.window_text().strip()
                    except Exception:
                        continue
                    if t and len(t) > 1:
                        texts.append(t)
                dbg(f"  all descendants with text: {len(texts)}")
            else:
                dbg("chat area NOT found")
        finally:
            _unlock()

    if not texts:
        dbg("FAIL: no text from chat area")
        return ""

    dbg(f"OK: {len(texts)} lines, last: {texts[-1][:50]}")
    return "\n".join(texts[-5:])
