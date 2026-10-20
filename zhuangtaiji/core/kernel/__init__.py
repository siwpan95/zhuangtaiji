# -*- coding: utf-8 -*-
"""
core.kernel —— 内核：Context / effect / inject / 事件派发 / 分层装配
==================================================================

这不是 Cordis 的 Python 移植（Cordis 是 TypeScript），而是**把它的四条核心
纪律提炼成 Python 惯用法**，用于承载本项目的引擎与编排：

1. ``Context`` 服务容器 —— 取代过去的模块级全局状态
   （``GUARD_REGISTRY`` / ``ACTION_REGISTRY`` / ``_ADAPTERS`` / ``_SECTION_OF``
   / ``PluginRegistry._plugins`` / ``web.server.ORCH``）；
2. ``effect`` 注册即可逆 —— 每一次注册都返回可撤销句柄，owner 卸载时逆序回收；
3. ``inject`` 声明依赖 —— **加载顺序由服务可得性决定，不由代码顺序决定**；
4. 空根 + 分层 patch —— 配置是数据，``apply_patches`` 是唯一纯函数。

设计取舍（刻意**不**移植 Cordis 的实现细节）：

* 不实现 Proxy + trap，改用 ``__getattr__``（Python 惯用法，可读性更好）；
* 不实现 6 态 fiber，只用 ``PENDING / ACTIVE / FAILED / DISPOSED`` 四态；
* 不做 epoch 字符串指纹，改用显式 ``_recheck()`` 遍历
  （规模上到数百插件时可替换为 ``core.difference_engine.ReactiveTracker``）；
* 全程同步：本项目没有异步运行时，``effect`` 不返回 awaitable。

内核自身的生命周期模型见 ``fiber_model.json``——它使用本项目自己的状态机
配置格式书写，并由 ``test/test_kernel.py`` 的锁步一致性用例验证。
"""
from .context import ACTIVE, DISPOSED, FAILED, PENDING, Context, Plugin
from .disposable import Disposable, DisposableList
from .events import MODES, EventBus
from .loader import (
    ENTRY_META,
    Layer,
    Loader,
    Patch,
    apply_patches,
    build_index,
    compose,
    hot_reload,
)
from .registry import Registry, RegistryView, make_default_context

__all__ = [
    "Context", "Plugin",
    "ACTIVE", "PENDING", "DISPOSED", "FAILED",
    "Disposable", "DisposableList",
    "EventBus", "MODES",
    "Loader", "apply_patches", "compose", "build_index", "hot_reload",
    "Layer", "Patch", "ENTRY_META",
    "Registry", "RegistryView", "make_default_context",
]
