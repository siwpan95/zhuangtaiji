# -*- coding: utf-8 -*-
"""进程级注册表的统一归属：守卫 / 动作 / 引擎 / 插件。

**为什么单独一个模块**：过去这些注册表是 ``core/state_machine.py`` 里的模块级
字典，而 ``hierarchical_state_machine.py`` 需要读它们——于是只能写成函数内的
内联 ``from .state_machine import GUARD_REGISTRY``（因为 ``state_machine`` 反过来
又 import 了 ``hierarchical_state_machine``，顶部 import 会成环）。

把这些注册表提到中立的 ``core.registries``，两个状态机模块都可以在顶部正常
import，环被解开；同时它们统一由内核 ``Context`` 承载，因而具备：

* **可撤销**——``register_guard`` / ``register_action`` 返回 ``Disposable``；
* **fail-loud**——重复注册立刻抛错，不再静默覆盖；
* **可自省**——``*.describe()`` 供 UI 与诊断枚举，无需硬编码。

对既有读取方保持 dict 兼容（``GUARD_REGISTRY`` / ``ACTION_REGISTRY`` 是
``RegistryView``）：``.get()`` / ``[]`` / ``in`` / 迭代都照常工作，
但**赋值被禁止**，以免绕过 disposer 追踪。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .kernel import make_default_context
from .kernel.registry import RegistryView

#: 进程默认 context。所有注册表都挂在它上面——"全局"从此是一个显式对象，
#: 因此可被整体替换、可在测试中隔离、可被自省枚举。
context, _registries = make_default_context("context")

#: 守卫注册表（可写，带撤销）。
guards = _registries["guards"]
#: 动作注册表（可写，带撤销）。
actions = _registries["actions"]
#: 引擎 kind 注册表（可写，带撤销）。
engines = _registries["engines"]
#: 插件 kind 注册表（可写，带撤销）。
plugins = _registries["plugins"]

#: dict 兼容的只读视图：供历史代码以 ``GUARD_REGISTRY.get(...)`` 读取。
GUARD_REGISTRY: RegistryView = RegistryView(guards)
#: dict 兼容的只读视图：供历史代码以 ``ACTION_REGISTRY.get(...)`` 读取。
ACTION_REGISTRY: RegistryView = RegistryView(actions)


@dataclass(frozen=True)
class EngineKind:
    """一种引擎范式的注册信息。

    这张小结构取代了过去散落在六处的 ``kind -> config 段名`` 映射：

    ==================================  ==========================================
    位置                                  形式
    ==================================  ==========================================
    ``core/engine_adapters.py:403``       ``_ADAPTERS``（kind → 类）
    ``core/engine_adapters.py:413``       ``_SECTION_OF``（kind → 段名）
    ``core/plugin.py:99-133``             7 次 ``_section_provider("…")``
    ``web/server.py:179``                 kind → 段名（供 engine step 端点）
    ``web/server.py:334``                 kind → 段名（供 api/engines）
    ``ui/analysis_tab.py:17``             (kind, 段名, 标签) 硬编码列表
    ``ui/visualization_tab.py:19``        同上，又一份
    ==================================  ==========================================

    新增一个范式过去需要在上述位置逐处补写，漏一处就出现"某个入口看不到新范式"。
    现在只需 ``register_engine()`` 一次，所有消费方（Web 端点、UI Tab、编排层、
    插件注册表）都从注册表派生。
    """

    kind: str
    adapter_cls: Any
    section: str
    label: str = ""
    description: str = ""


def register_engine(kind: str, adapter_cls: Any, section: str,
                    label: str = "", description: str = "") -> Any:
    """注册一种引擎范式。

    :param kind: 唯一标识（config 的 ``engines.<alias>.kind`` 引用它）。
    :param adapter_cls: 适配器类，签名 ``(name=..., on_event=...) -> BaseAdapter``。
    :param section: 该范式在 ``config.json`` 中的顶层段名，如 ``"state_machines"``。
    :param label: 展示名（UI Tab 标题）。
    :param description: 一句话说明（UI 提示）。
    :returns: ``Disposable``；撤销后该范式从所有入口一并消失。
    :raises KeyError: kind 已注册。
    """
    return engines.register(
        kind, EngineKind(kind, adapter_cls, section, label or kind, description))


def engine_kinds() -> List[EngineKind]:
    """已注册的全部引擎范式，按 kind 排序（自省 / UI 渲染的单一数据源）。"""
    return sorted(engines.values(), key=lambda e: e.kind)


def engine_of(kind: str) -> Optional[EngineKind]:
    """按 kind 查引擎范式；不存在返回 ``None``。"""
    return engines.get(kind)


def engine_sections() -> Dict[str, str]:
    """``{kind: config 段名}``——取代过去在多处重复的映射表。"""
    return {e.kind: e.section for e in engine_kinds()}


def register_guard(name: str, fn: Callable):
    """注册命名守卫，供 config 的 ``guard`` 字段引用。

    :param name: 守卫名。
    :param fn: ``(context: dict) -> bool``；返回假值即拒绝该转移。
    :returns: ``Disposable``；撤销后该守卫对所有实例（含已创建）立即失效。
    :raises KeyError: 同名守卫已注册。
    """
    return guards.register(name, fn)


def register_action(name: str, fn):
    """注册命名动作，供 state 的 ``on_enter`` / ``on_exit`` 引用。

    :param name: 动作名（须与 config 中的字符串完全一致）。
    :param fn: ``(context: dict, detail: dict) -> None``。
    :returns: ``Disposable``；撤销后该动作立即失效。
    :raises KeyError: 同名动作已注册。
    """
    return actions.register(name, fn)
