# -*- coding: utf-8 -*-
"""多范式决策引擎 · zhuangtaiji

把多种计算/决策范式连成「可编排系统」的 Python 引擎（**纯标准库实现，零第三方依赖**）：

* 状态机 ``FSM`` / 层次状态机 ``HSM``
* 行为树 ``Behavior Tree``
* 决策树 ``Decision Tree``
* 差分机 ``Difference Engine``
* Petri 网 ``Petri Net``
* 马尔可夫链 ``Markov Chain``
* 规则引擎 ``Rule Engine``（Rete 风格前向链）
* 决策表 / LLM 智能体（以插件形态接入）

顶层已重导出 :mod:`zhuangtaiji.core` 的全部公开 API，因此::

    from zhuangtaiji import load_config, create_state_machine

等价于::

    from zhuangtaiji.core import load_config, create_state_machine

图形界面（Tkinter 工作台）与 Web 编排服务位于 ``zhuangtaiji.ui`` /
``zhuangtaiji.web``，它们**不在**顶层自动导入——因为 ``ui`` 需要 tkinter、
``web`` 需要前端构建产物，按需导入可以避免无头环境（CI / 容器）被拖垮::

    python -m zhuangtaiji            # 启动 Tkinter 工作台
    python -m zhuangtaiji.web.server # 启动 Web 编排服务（默认 127.0.0.1:8011）
"""
from __future__ import annotations

__version__ = "1.1.0"
__all__ = ["core", "engine", "__version__"]

from . import core  # noqa: E402,F401
from . import engine  # noqa: E402,F401   （progress_bar 内部延迟导入 tkinter，无头安全）
from .core import *  # noqa: E402,F401,F403
