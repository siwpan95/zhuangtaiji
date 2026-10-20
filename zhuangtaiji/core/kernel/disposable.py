# -*- coding: utf-8 -*-
"""
可逆注册的基元（对应 Cordis 的 Disposable / effect 语义）
=====================================================

Cordis 的核心纪律是「注册即 effect，卸载即回收」。Python 里落地为：

* ``Disposable`` —— 一次性的清理句柄。重复调用是 no-op（单次性），
  且保留首次结果（对应 Cordis wrapper 的 epoch 闸门）。
* ``DisposableList`` —— 逆序回收（后注册先清理）的容器。

逆序回收是刻意选择：它给出「先建立的依赖后拆」的直觉顺序，
与 Cordis ``Fiber.effect`` 内部的 ``splice(0).reverse()`` 一致。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, List, Optional


class Disposable:
    """单次性清理句柄。

    与 Cordis 一致的两条契约：

    1. **单次性**：第二次 ``dispose()`` 不再执行清理体，直接返回首次结果。
    2. **可 join**：句柄可被多个 owner 持有；无论谁先调用，清理体只跑一次。
    """

    __slots__ = ("_fn", "_label", "_called", "_result")

    def __init__(self, fn: Optional[Callable[[], Any]] = None, label: str = ""):
        self._fn = fn
        self._label = label
        self._called = False
        self._result: Any = None

    @property
    def disposed(self) -> bool:
        """清理体是否已执行。"""
        return self._called

    @property
    def label(self) -> str:
        return self._label

    def dispose(self) -> Any:
        """执行清理体；已执行则直接返回首次结果。清理体异常不外抛。"""
        if self._called:
            return self._result
        self._called = True
        fn, self._fn = self._fn, None
        if fn is None:
            return None
        try:
            self._result = fn()
        except Exception as exc:  # 清理期异常不该阻断兄弟清理
            self._result = exc
            print(f"[kernel] dispose failed ({self._label or 'unnamed'}): {exc!r}")
        return self._result

    # 允许把 Disposable 当函数调用，贴近 Cordis 的 `const dispose = ctx.effect(...)`
    __call__ = dispose

    @classmethod
    def of(cls, value: Any, label: str = "") -> "Disposable":
        """把任意返回值归一化为 Disposable。

        支持 ``None`` / ``Disposable`` / 可调用对象 / 它们的列表。
        """
        if value is None:
            return cls(None, label)
        if isinstance(value, Disposable):
            return value
        if callable(value):
            return cls(value, label or getattr(value, "__name__", ""))
        if isinstance(value, (list, tuple)):
            items = [cls.of(v, label) for v in value]
            return cls(lambda: [d.dispose() for d in items], label)
        raise TypeError(f"cannot normalize {type(value).__name__} into Disposable")


class DisposableList:
    """逆序回收的清理句柄集合。"""

    def __init__(self) -> None:
        self._items: List[Disposable] = []

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterable[Disposable]:
        return iter(list(self._items))

    def add(self, item: Disposable) -> Disposable:
        self._items.append(item)
        return item

    def remove(self, item: Disposable) -> bool:
        """按身份摘除一个句柄（不执行清理）；返回是否命中。"""
        for i, existing in enumerate(self._items):
            if existing is item:
                self._items.pop(i)
                return True
        return False

    def dispose(self) -> None:
        """逆序回收全部句柄，然后清空。

        单个句柄失败不中断其余回收（``Disposable.dispose`` 内部已吞异常）。
        """
        items = self._items[:]
        self._items.clear()
        for d in reversed(items):
            d.dispose()

    def rollback(self) -> None:
        """失败回滚：清空收集到的句柄并逆序执行。"""
        self.dispose()
