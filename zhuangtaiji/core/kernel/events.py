# -*- coding: utf-8 -*-
"""
类型化事件总线（对应 Cordis 的 Events / 五种派发模式）
=================================================

现状对照：``core/orchestrator.py`` 的 ``EventBus`` 有两个硬缺口——

1. ``subscribe()`` / ``subscribe_all()`` **返回 None**，没有退订手段；
2. ``publish()`` 只有一种「同步广播」，没有拦截/改写/短路能力。

本模块给出修正版的语义：

* ``on(name, cb, mode=...)`` **返回 Disposable**，注册挂在 owner 的 effect 上；
* 支持三种对本项目真正有用的派发模式：

  ============== ========== ===================== ==========================
  模式            同步/顺序   返回值                 短路条件
  ============== ========== ===================== ==========================
  ``emit``        同步·注册序  丢弃                   无
  ``waterfall``   同步·注册序  有（围绕中间件）        不调用 next
  ``serial``      同步·注册序  有（首个非 None 胜出）  首个非 None
  ============== ========== ===================== ==========================

**派发模式是事件公开契约的一部分**：同一个事件名首次注册时确定模式，
之后不一致的注册直接报错（fail loud），避免"某个监听器静默不生效"。
这是 Cordis「dispatch mode is part of the event's public contract」的直译。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from .disposable import Disposable

MODES = ("emit", "waterfall", "serial")


class EventBus:
    """按事件名分派监听器的总线；所有注册返回 Disposable。"""

    def __init__(self) -> None:
        # name -> [(callback, prepend)]
        self._hooks: Dict[str, List[Tuple[Callable, bool]]] = {}
        # name -> 已声明的派发模式（契约）
        self._modes: Dict[str, str] = {}
        self._dispatch_log: List[Tuple[str, str]] = []

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------
    def on(self, name: str, cb: Callable, mode: str = "emit",
           prepend: bool = False) -> Disposable:
        """注册监听器，返回可撤销句柄。

        :param name: 事件名，如 ``"engine/step"``。
        :param cb: 监听器。``emit`` 收 ``(payload)``；``waterfall`` 收
            ``(payload, next_)`` 且必须调用 ``next_`` 才继续；``serial`` 收
            ``(payload)`` 并返回非 None 表示短路。
        :param mode: 派发模式，见模块文档。
        :param prepend: 是否插队到最前（仅在"必须先跑"时使用）。
        :raises ValueError: 事件名已声明为其它模式。
        """
        if mode not in MODES:
            raise ValueError(f"unknown dispatch mode: {mode!r}")

        declared = self._modes.get(name)
        if declared is None:
            self._modes[name] = mode
        elif declared != mode:
            raise ValueError(
                f'event "{name}" is declared as {declared!r} but '
                f"registered as {mode!r}; dispatch mode is part of the contract"
            )

        entry: Tuple[Callable, bool] = (cb, prepend)
        bucket = self._hooks.setdefault(name, [])
        if prepend:
            bucket.insert(0, entry)
        else:
            bucket.append(entry)

        def _off() -> None:
            items = self._hooks.get(name)
            if not items:
                return
            for i, item in enumerate(items):
                if item is entry:
                    items.pop(i)
                    break
            if not items:
                self._hooks.pop(name, None)
                self._modes.pop(name, None)

        return Disposable(_off, label=f"on:{name}")

    def mode_of(self, name: str) -> Optional[str]:
        """该事件已声明的派发模式；未注册过为 None。"""
        return self._modes.get(name)

    def listener_count(self, name: str) -> int:
        """指定事件名的监听器数量。"""
        return len(self._hooks.get(name, ()))

    def names(self) -> List[str]:
        """当前有监听器的事件名（供诊断与"监听器是否泄漏"的断言）。"""
        return list(self._hooks)

    def total_listeners(self) -> int:
        """全部监听器数量。"""
        return sum(len(v) for v in self._hooks.values())

    def clear(self) -> None:
        """清空全部监听器（由 owner 的 dispose 调用）。"""
        self._hooks.clear()
        self._modes.clear()

    # ------------------------------------------------------------------
    # 分派
    # ------------------------------------------------------------------
    def emit(self, name: str, payload: Any = None) -> None:
        """同步广播，按注册序；返回值丢弃；单个监听器异常不阻断其余。"""
        self._dispatch_log.append(("emit", name))
        for cb, _ in list(self._hooks.get(name, ())):
            try:
                cb(payload)
            except Exception as exc:
                print(f"[kernel] listener failed on {name}: {exc!r}")

    def waterfall(self, name: str, payload: Any,
                  inner: Optional[Callable[[Any], Any]] = None) -> Any:
        """围绕中间件：监听器收 ``(payload, next_)``，不调 ``next_`` 即短路。

        :param inner: 链条最内层的"原始行为"。无监听器时直接执行它。
        :returns: 最外层监听器的返回值（或 ``inner`` 的结果）。
        """
        self._dispatch_log.append(("waterfall", name))
        cbs = [cb for cb, _ in self._hooks.get(name, ())]

        def step(i: int, value: Any) -> Any:
            if i >= len(cbs):
                return inner(value) if inner else value

            def next_(value2: Any) -> Any:
                return step(i + 1, value2)

            return cbs[i](value, next_)

        return step(0, payload)

    def serial(self, name: str, payload: Any = None) -> Any:
        """顺序执行，首个非 None 返回值短路并作为结果（bail 语义）。"""
        self._dispatch_log.append(("serial", name))
        for cb, _ in list(self._hooks.get(name, ())):
            try:
                result = cb(payload)
            except Exception as exc:
                print(f"[kernel] listener failed on {name}: {exc!r}")
                continue
            if result is not None:
                return result
        return None
