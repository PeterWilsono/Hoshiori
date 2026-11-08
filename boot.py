# -*- coding: utf-8 -*-
"""启动计时。

“为什么点开之后要等这么久”这类问题，只能靠时间戳回答。
所有关键节点都往 app.log 里打一行 [启动 xxx ms]，出问题时翻日志就能定位。
"""

import sys
import time

T0 = time.perf_counter()


def ms():
    """从解释器拿到控制权算起，已经过了多少毫秒。"""
    return (time.perf_counter() - T0) * 1000.0


def log(label):
    """打一行启动日志；没有 stdout（无控制台打包）时静默跳过。"""
    if sys.stdout is None:
        return
    try:
        print("[启动 %6.0f ms] %s" % (ms(), label), flush=True)
    except Exception:
        pass
