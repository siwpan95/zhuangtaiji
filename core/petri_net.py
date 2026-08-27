# -*- coding: utf-8 -*-
"""
Petri 网（Petri Net）
====================

Petri 网由 Carl Adam Petri 于 1962 年提出，是描述**分布式、并发、异步**系统
的强有力数学工具。它用一张「二部图」表达系统：

  * Place（库所，○ 圆圈）：表示「条件 / 资源 / 状态」，内部可容纳若干 Token（令牌）。
  * Transition（变迁，▮ 竖条）：表示「事件 / 动作」。
  * Arc（弧，→）：连接 Place 与 Transition，可带**权重**（weight）。

形式化定义（参考 Murata 1989, TUM / Uni Bern 讲义）：
  PN = (P, T, F, W, M₀)
    P : 库所集合          T : 变迁集合 (P∩T=∅)
    F : 流关系（有向弧）   W : 弧权重函数
    M : 标记（marking），M(p) = 库所 p 中的令牌数

**使能 (enabled)**：一个变迁 t 使能，当且仅当它的每个输入库所 p 拥有
  M(p) ≥ W(p, t) 个令牌；若含**抑制弧 (inhibitor arc)**，则要求
  M(p) < W(p, t) 才允许触发。

**触发 (firing)**：t 触发时，从每个输入库所减去 W(p,t) 个令牌，
  向每个输出库所增加 W(t,p) 个令牌。

工程价值
--------
* 天然刻画**并发**（多个变迁可同时使能）与**资源竞争**（令牌即资源）。
* 比 FSM 更适合「多条件同时满足才触发动作」的供应链 / 工作流场景。
* 可判定性质：可达性、有界性、死锁（本模块提供 enabled/fire 与简单死锁检测）。

本模块同时提供：命令式构建 + 声明式 build_petri_net(spec)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ==========================================
# 基本元素
# ==========================================
class Transition:
    """变迁：持有输入/输出/抑制弧（均为 (place, weight)）。"""

    def __init__(self, name: str,
                 inputs: Optional[List[Tuple[str, int]]] = None,
                 outputs: Optional[List[Tuple[str, int]]] = None,
                 inhibitors: Optional[List[Tuple[str, int]]] = None,
                 priority: int = 0):
        self.name = name
        self.inputs: List[Tuple[str, int]] = list(inputs or [])
        self.outputs: List[Tuple[str, int]] = list(outputs or [])
        self.inhibitors: List[Tuple[str, int]] = list(inhibitors or [])
        self.priority = priority

    def __repr__(self):
        return (f"<Transition {self.name!r} in={self.inputs} "
                f"out={self.outputs} inh={self.inhibitors}>")


# ==========================================
# Petri 网
# ==========================================
class PetriNet:
    def __init__(self, name: str = "PetriNet",
                 places: Optional[Dict[str, int]] = None,
                 transitions: Optional[Dict[str, Transition]] = None):
        self.name = name
        self.places: Dict[str, int] = dict(places or {})
        self.transitions: Dict[str, Transition] = dict(transitions or {})

    # ---------- 标记 ----------
    def marking(self) -> Dict[str, int]:
        return dict(self.places)

    def set_tokens(self, place: str, n: int) -> None:
        if place not in self.places:
            raise KeyError(f"未知库所: {place}")
        if n < 0:
            raise ValueError("令牌数不能为负")
        self.places[place] = n

    def add_tokens(self, place: str, n: int = 1) -> None:
        self.set_tokens(place, self.places.get(place, 0) + n)

    # ---------- 使能判定 ----------
    def is_enabled(self, tname: str) -> bool:
        t = self.transitions.get(tname)
        if not t:
            return False
        # 输入弧：令牌足够
        for p, w in t.inputs:
            if self.places.get(p, 0) < w:
                return False
        # 抑制弧：令牌必须 < 权重
        for p, w in t.inhibitors:
            if self.places.get(p, 0) >= w:
                return False
        return True

    def enabled_transitions(self) -> List[str]:
        return [name for name in self.transitions
                if self.is_enabled(name)]

    def is_deadlock(self) -> bool:
        """没有任何使能变迁即视为死锁（终止）状态。"""
        return not any(self.is_enabled(n) for n in self.transitions)

    # ---------- 触发 ----------
    def fire(self, tname: str) -> bool:
        """触发一个变迁，成功返回 True。"""
        if not self.is_enabled(tname):
            return False
        t = self.transitions[tname]
        for p, w in t.inputs:
            self.places[p] -= w
        for p, w in t.outputs:
            self.places[p] = self.places.get(p, 0) + w
        return True

    def step(self, strategy: str = "priority") -> List[str]:
        """推进一个原子步：触发若干个使能变迁。

        strategy:
          "one"     只触发优先级最高（priority 大者）的一个；
          "all"     同时触发所有使能变迁（并行语义）；
          "priority"= "one"（默认）。
        返回本次实际触发的变迁名列表。
        """
        enabled = self.enabled_transitions()
        if not enabled:
            return []
        if strategy == "all":
            fired = []
            for n in enabled:
                if self.fire(n):
                    fired.append(n)
            return fired
        # one / priority：选优先级最高，其次字典序
        best = sorted(enabled,
                      key=lambda n: (-self.transitions[n].priority, n))[0]
        self.fire(best)
        return [best]

    def run(self, max_steps: int = 1000, strategy: str = "priority",
            on_step=None) -> List[Dict[str, int]]:
        """连续触发直到死锁或达到 max_steps，返回每一步后的标记轨迹。"""
        trace = [self.marking()]
        for _ in range(max_steps):
            fired = self.step(strategy=strategy)
            if not fired:
                break
            if callable(on_step):
                on_step(fired, self.marking())
            trace.append(self.marking())
        return trace

    # ---------- 可视化 ----------
    def format_marking(self) -> str:
        parts = [f"{p}={self.places[p]}" for p in self.places]
        return " | ".join(parts)

    def __repr__(self):
        return (f"<PetriNet {self.name!r} places={len(self.places)} "
                f"transitions={len(self.transitions)} "
                f"marking=({self.format_marking()})>")


# ==========================================
# 声明式构建
# ==========================================
def _parse_arcs(spec: Any) -> List[Tuple[str, int]]:
    """弧可写作 [["p1", 1], ["p2", 2]] 或 {"p1":1, "p2":2}。"""
    if isinstance(spec, dict):
        return [(k, int(v)) for k, v in spec.items()]
    out = []
    for item in (spec or []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.append((str(item[0]), int(item[1])))
        else:
            out.append((str(item), 1))
    return out


def build_petri_net(spec: Dict[str, Any]) -> PetriNet:
    """由声明式规格构造 PetriNet。

    spec 形如：
        {
          "name": "订单履约",
          "places": {"p_inventory": 2, "p_order": 0, "p_pack": 0, "p_ship": 0},
          "transitions": {
            "t_pick": {
              "inputs":  [["p_inventory", 1]],
              "outputs": [["p_order", 1]],
              "priority": 1
            },
            "t_pack": {
              "inputs":  [["p_order", 1]],
              "outputs": [["p_pack", 1]]
            },
            "t_ship": {
              "inputs":  [["p_pack", 1]],
              "outputs": [["p_ship", 1], ["p_inventory", 1]]  # 库存回流
            },
            "t_halt": {                       # 抑制弧示例
              "inputs":  [],
              "outputs": [["p_ship", 1]],
              "inhibitors": [["p_pack", 1]]   # 仅当 p_pack 无令牌时才能直接发货
            }
          }
        }
    """
    places = {k: int(v) for k, v in (spec.get("places") or {}).items()}
    transitions: Dict[str, Transition] = {}
    for tname, tspec in (spec.get("transitions") or {}).items():
        transitions[tname] = Transition(
            name=tname,
            inputs=_parse_arcs(tspec.get("inputs")),
            outputs=_parse_arcs(tspec.get("outputs")),
            inhibitors=_parse_arcs(tspec.get("inhibitors")),
            priority=int(tspec.get("priority", 0)),
        )
    return PetriNet(name=spec.get("name", "PetriNet"),
                    places=places, transitions=transitions)
