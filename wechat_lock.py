"""WeChat 操作锁：所有 pyweixin 调用必须通过此锁串行化"""

import threading

wechat_lock = threading.Lock()
