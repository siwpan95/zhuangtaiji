# -*- coding: utf-8 -*-
"""
Registry —— 可撤销、fail-loud 的通用注册表
=========================================

本项目过去有四处"注册表"，各自实现、各自为政：

======================  ==========================================
位置                     内容
======================  ==========================================
``GUARD_REGISTRY``       守卫名 → 可调用对象（state_machine.py:11）
``ACTION_REGISTRY``      动作名 → 可调用对象（state_machine.py:25）
``_ADAPTERS``            引擎 kind → 适配器类（engine_adapters.py:403）
``PluginRegistry``       引擎 kind → EnginePlugin（plugin.py:47）
======================  ==========================================

它们有三个共同缺陷：

1. **注册不可撤销**——没有 ``unregister``，测试之间互相污染；
2. **静默覆盖**——``d[k] = v`` 形式，重复注册不报错，后写悄悄吃掉先写；
3. **无自省**——UI 与 Web 端点只能靠硬编码列表知道"有哪些"。

``Registry`` 统一这三件事：

* ``register(key, value)`` **返回 ``Disposable``**，撤销即移除；
* 重复注册**立即抛错**（要覆盖请显式用 ``replace``）；
* 提供 ``keys/items/describe``，供自省与 UI 动态渲染。

设计上刻意保持"哑容器"：它不理解值的语义。需要语义（如"必须是 BaseAdapter
子类"）由调用方在注册前校验——这样同一个 Registry 能服务守卫、动作、引擎三
种完全不同的场景，而不必为每种写一个类。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .disposable import Disposable


class Registry:
    """键值注册表：注册返回可撤销句柄，重复键 fail-loud。

    :param name: 注册表名，用于日志与变更事件（如 ``"engines"``）。
    :param ctx: 可选的宿主 context；提供后每次变更会发出 ``<name>/registered``
        与 ``<name>/unregistered`` 事件，供 UI 增量刷新（无需轮询）。
    :param describe: 可选的值描述器 ``value -> str``，供自省展示。
    """

    def __init__(self, name: str, ctx: Any = None,
                 describe: Optional[Callable[[Any], str]] = None):
        self.name = name
        self._ctx = ctx
        self._describe = describe or (lambda v: type(v).__name__)
        self._items: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 注册 / 撤销
    # ------------------------------------------------------------------
    def register(self, key: str, value: Any) -> Disposable:
        """注册一个条目，返回撤销句柄。

        :raises KeyError: 键已存在。这取代了过去的静默覆盖——
            重复注册几乎总是 bug（两个插件抢同一个 kind），必须立刻暴露。
        """
        if key in self._items:
            raise KeyError(
                f'{self.name}: "{key}" is already registered '
                f"({self._describe(self._items[key])}); "
                f"use replace() to swap it explicitly"
            )
        self._items[key] = value
        self._notify("registered", key, value)

        def _off() -> None:
            if self._items.pop(key, None) is not None:
                self._notify("unregistered", key, value)

        return Disposable(_off, label=f"{self.name}:{key}")

    def replace(self, key: str, value: Any) -> Disposable:
        """原子替换已存在的条目（provider swap）。键不存在则等同于 ``register``。"""
        self._items[key] = value
        self._notify("registered", key, value)

        def _off() -> None:
            if self._items.get(key) is value:
                self._items.pop(key, None)
                self._notify("unregistered", key, value)

        return Disposable(_off, label=f"{self.name}:{key}")

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._items.get(key, default)

    def require(self, key: str) -> Any:
        """取条目，缺失即报错并列出可用键（便于定位配置写错）。"""
        if key not in self._items:
            raise KeyError(
                f'{self.name}: "{key}" is not registered; '
                f"available: {sorted(self._items)}"
            )
        return self._items[key]

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._items))

    def keys(self) -> List[str]:
        return list(self._items)

    def values(self) -> List[Any]:
        return list(self._items.values())

    def items(self) -> List[Tuple[str, Any]]:
        return list(self._items.items())

    def describe(self) -> Dict[str, str]:
        """``{key: 描述}`` 快照——自省与 UI 渲染的单一数据源。"""
        return {k: self._describe(v) for k, v in self._items.items()}

    def clear(self) -> None:
        """清空全部条目（由 owner 的 dispose 调用）。"""
        for key, value in list(self._items.items()):
            self._items.pop(key, None)
            self._notify("unregistered", key, value)

    # ------------------------------------------------------------------
    def _notify(self, action: str, key: str, value: Any) -> None:
        if self._ctx is not None:
            try:
                self._ctx.emit(f"{self.name}/{action}", {"key": key, "value": value})
            except Exception as exc:       # 通知失败不得影响注册本身
                print(f"[kernel] registry notify failed ({self.name}/{action}): {exc!r}")

    def __repr__(self) -> str:
        return f"<Registry {self.name} size={len(self._items)}>"


class RegistryView(Mapping):
    """``Registry`` 的**只读**映射视图，提供 dict 兼容的读接口。

    用途：让历史上名为 ``GUARD_REGISTRY`` / ``ACTION_REGISTRY`` 的模块级变量
    继续以 ``.get()`` / ``[]`` / ``in`` / 迭代的方式被读取，而底层换成可撤销的
    ``Registry``——**迁移因此不需要改动任何读取方**。

    **赋值被显式禁止**（``__setitem__`` 抛 ``TypeError``）。这是刻意的：
    过去的 ``GUARD_REGISTRY[name] = fn`` 正是"注册不可撤销"的根源——
    绕过 ``register()`` 就没有 disposer 可追踪。禁止赋值让"注册必须可撤销"
    无法被绕过，并把错误信息指向正确的 API。
    """

    def __init__(self, registry: "Registry"):
        self._registry = registry

    def __getitem__(self, key: str) -> Any:
        return self._registry.require(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._registry.keys())

    def __len__(self) -> int:
        return len(self._registry)

    def get(self, key: str, default: Any = None) -> Any:
        return self._registry.get(key, default)

    def keys(self) -> List[str]:
        return self._registry.keys()

    def values(self) -> List[Any]:
        return self._registry.values()

    def items(self) -> List[Tuple[str, Any]]:
        return self._registry.items()

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError(
            f'{self._registry.name}: direct assignment is not allowed '
            f"(would register without a disposer). "
            f'Use registry.register("{key}", value) / register_guard(...) instead.'
        )

    def __delitem__(self, key: str) -> None:
        raise TypeError(
            f'{self._registry.name}: direct deletion is not allowed; '
            f"keep the Disposable returned by register() and call dispose()"
        )

    def __repr__(self) -> str:
        return f"<RegistryView {self._registry.name} size={len(self._registry)}>"


def make_default_context(name: str = "host"):
    """构造一个进程默认 context，并挂上本项目需要的四张注册表。

    这是"从全局字典迁移到 ctx"的落点：旧模块改为持有这个 ctx 提供的注册表，
    而不是各自的模块级字典。**它让"全局"变成"一个显式对象"**——
    因此可以（a）被整体替换、（b）在测试里隔离、（c）被自省枚举。

    :param name: context 名称，用于诊断输出。
    :returns: ``(ctx, registries)``；``registries`` 是 ``{name: Registry}``，
        键为 ``guards`` / ``actions`` / ``engines`` / ``plugins``。
    """
    from .context import Context

    ctx = Context(name=name)
    regs = {
        "guards": Registry("guards", ctx, describe=lambda v: getattr(v, "__name__", "?")),
        "actions": Registry("actions", ctx, describe=lambda v: getattr(v, "__name__", "?")),
        "engines": Registry("engines", ctx, describe=lambda v: getattr(v, "label", "?")),
        "plugins": Registry("plugins", ctx, describe=lambda v: getattr(v, "label", "?")),
    }
    # 通过 effect 注册：ctx 卸载时注册表随之撤销（注册即 effect）
    for key, reg in regs.items():
        ctx.effect(lambda k=key, r=reg: ctx.provide(k, r), label=f"registry:{key}")
    return ctx, regs
    return ctx, regs
