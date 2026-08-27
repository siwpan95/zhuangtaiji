# -*- coding: utf-8 -*-
"""
差分引擎（Difference Engine）
================================

「差分机」（Difference Engine）由查尔斯·巴贝奇于 1822 年提出，利用
**有限差分法** 将多项式求值转化为反复做加法——只需保存若干阶差分，
每前进一步只需做几次加法即可得到下一个函数值，从而用纯机械装置自动造表。

本模块把这一思想抽取为两类实用能力，供工作流引擎复用：

1. FiniteDifference（数值差分）
   - 由多项式系数 / 初始值表，仅用加法递推后续函数值（forward differences）。
   - 体现「差分机」的核心：用差分代替乘法与幂运算。

2. StateDiff / ReactiveTracker（状态差量 / 响应式追踪）
   - 比较前后两次状态快照，产出「差分」(added / removed / changed)。
   - 仅当差量命中订阅的键时触发回调——一种轻量、确定性的「响应式 / 脏检查」，
     避免对整棵状态树盲目重算。这与现代 UI 框架 / 状态管理的「diff + 增量更新」同源。

适用场景
--------
* 进度预测：用历史进度点差分，预测下一步进度（无需重算。
* 配置热更新：仅对变更字段做处理。
* 工作流可视化：只有状态真正改变时才重绘。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ==========================================
# 1) 有限差分（巴贝奇差分机思想）
# ==========================================
class FiniteDifference:
    """基于有限差分的递推求值器。

    给定某个 n 次多项式的前 (n+1) 个函数值，可求出所有后续值——
    原理是：n 次多项式的 (n+1) 阶差分为 0，而 0 阶差分就是函数值本身。
    因此只要维护各阶差分，每前进一步只需沿对角线做加法即可。
    """

    def __init__(self, initial_values: List[float]):
        """
        Args:
            initial_values: 多项式在 x=0,1,2,... 处的前 (阶数+1) 个函数值。
                            例如二次函数 f(x)=x^2 给出 [0, 1, 4, 9]。
        """
        if len(initial_values) < 2:
            raise ValueError("至少需要 2 个初始值")
        self._orig = list(initial_values)
        # 各阶差分表（diffs[k] 为第 k 阶差分序列）
        self._diffs = self._build_diff_table(list(initial_values))
        self._max_order = len(self._diffs) - 1  # 多项式阶数
        self._count = len(initial_values)

    @staticmethod
    def _build_diff_table(values: List[float]) -> List[List[float]]:
        table = [list(values)]
        cur = values
        while len(cur) > 1:
            nxt = [cur[i + 1] - cur[i] for i in range(len(cur) - 1)]
            table.append(nxt)
            cur = nxt
        return table

    def step(self) -> float:
        """推进一步，返回下一个函数值。"""
        # 最高阶差分恒为最后一个值（常数），沿对角线向上累加
        for order in range(self._max_order, 0, -1):
            last = self._diffs[order][-1]
            self._diffs[order - 1].append(self._diffs[order - 1][-1] + last)
        value = self._diffs[0][-1]
        self._count += 1
        return value

    def generate(self, count: int) -> List[float]:
        """从当前位置再生成 count 个后续值。"""
        out = []
        for _ in range(count):
            out.append(self.step())
        return out

    @property
    def order(self) -> int:
        return self._max_order

    @property
    def count(self) -> int:
        return self._count

    def history(self) -> List[float]:
        return list(self._diffs[0])


# ==========================================
# 2) 状态差量（StateDiff）
# ==========================================
@dataclass
class DiffEntry:
    key: str
    kind: str          # "added" | "removed" | "changed"
    old: Any = None
    new: Any = None


class StateDiff:
    """比较两个字典快照，产出差量。"""

    @staticmethod
    def diff(old: Dict[str, Any], new: Dict[str, Any]) -> List[DiffEntry]:
        entries: List[DiffEntry] = []
        old_keys = set(old.keys())
        new_keys = set(new.keys())
        for k in old_keys - new_keys:
            entries.append(DiffEntry(k, "removed", old=old[k], new=None))
        for k in new_keys - old_keys:
            entries.append(DiffEntry(k, "added", old=None, new=new[k]))
        for k in old_keys & new_keys:
            if old[k] != new[k]:
                entries.append(DiffEntry(k, "changed", old=old[k], new=new[k]))
        return entries

    @staticmethod
    def summary(entries: List[DiffEntry]) -> str:
        if not entries:
            return "无变化"
        parts = []
        for e in entries:
            if e.kind == "added":
                parts.append(f"+{e.key}={e.new}")
            elif e.kind == "removed":
                parts.append(f"-{e.key}")
            else:
                parts.append(f"~{e.key}:{e.old}->{e.new}")
        return " | ".join(parts)


# ==========================================
# 3) 响应式追踪器（脏检查 + 差分回调）
# ==========================================
class ReactiveTracker:
    """保存状态快照，仅当差量命中订阅键时触发回调（确定性差分触发）。"""

    def __init__(self, initial: Optional[Dict[str, Any]] = None,
                 on_change: Optional[Callable[[List[DiffEntry], Dict[str, Any]], None]] = None):
        self._state: Dict[str, Any] = dict(initial or {})
        self._on_change = on_change
        # 订阅：键 -> 回调列表
        self._subscribers: Dict[str, List[Callable[[DiffEntry, Dict[str, Any]], None]]] = {}

    @property
    def state(self) -> Dict[str, Any]:
        return dict(self._state)

    def subscribe(self, key: str,
                  cb: Callable[[DiffEntry, Dict[str, Any]], None]) -> None:
        self._subscribers.setdefault(key, []).append(cb)

    def update(self, patch: Dict[str, Any]) -> List[DiffEntry]:
        """应用补丁（浅合并），返回差量并在必要时触发回调。"""
        new_state = dict(self._state)
        new_state.update(patch)
        entries = StateDiff.diff(self._state, new_state)

        # 全局回调
        if entries and callable(self._on_change):
            self._on_change(entries, new_state)

        # 键级订阅回调
        for e in entries:
            for cb in self._subscribers.get(e.key, []):
                cb(e, new_state)

        self._state = new_state
        return entries

    def set(self, key: str, value: Any) -> List[DiffEntry]:
        return self.update({key: value})


# ==========================================
# 便捷构造：从配置构建
# ==========================================
def build_finite_difference(spec: Dict[str, Any]) -> FiniteDifference:
    return FiniteDifference(spec.get("initial_values", []))


def build_reactive_tracker(spec: Dict[str, Any],
                           on_change=None) -> ReactiveTracker:
    return ReactiveTracker(initial=spec.get("initial", {}), on_change=on_change)
