# -*- coding: utf-8 -*-
"""
统一引擎契约（P0-1 基石）
========================

本项目有 7 个范式引擎，API 各异（trigger / tick / decide / fire / step）。
为使 UI、插件、编排层能「对一类引擎编程」而非逐个 hard-code，这里定义一套
统一契约：

* ``EngineResult`` —— 所有引擎 step() 的标准返回（值 + 详情 + 轨迹）。
* ``Graph`` / ``GraphNode`` / ``GraphEdge`` —— 统一的图模型，供渲染层导出
  Mermaid / DOT / ASCII，并携带 ``active`` 标记以支持「执行轨迹高亮」。
* ``EngineEvent`` —— 跨引擎事件（供编排层 Orchestrator 使用）。
* ``Engine`` —— 协议（结构化契约），各范式通过 ``engine_adapters`` 适配。

适配器模式而非强制子类化：既尊重开闭原则，又避免改动现有引擎内核。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ==========================================================
# 统一结果
# ==========================================================
@dataclass
class EngineResult:
    """所有引擎 step() 的标准返回。"""
    kind: str = "generic"            # state | trace | decision | marking | distribution | facts
    value: Any = None                # 主结果（状态名 / 标签 / 路径序列 ...）
    detail: Dict[str, Any] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)  # 逐步记录，供轨迹回放


# ==========================================================
# 统一图模型（供可视化渲染）
# ==========================================================
@dataclass
class GraphNode:
    id: str
    label: str
    shape: str = "box"               # box | circle | rect | diamond | round
    style: str = ""                  # 颜色/样式提示
    active: bool = False             # 轨迹高亮（当前激活）
    sub_of: Optional[str] = None     # 所属子图（嵌套状态机）


@dataclass
class GraphEdge:
    src: str
    dst: str
    label: str = ""
    active: bool = False
    style: str = ""


@dataclass
class Graph:
    """通用图：节点 + 边 + 子图分组。"""
    kind: str = "flowchart"          # flowchart | stateDiagram
    direction: str = "TB"
    title: str = ""
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    subgraphs: Dict[str, List[str]] = field(default_factory=dict)  # id -> [node ids]

    def add_node(self, id: str, label: str, **kw) -> "GraphNode":
        node = GraphNode(id=id, label=label, **kw)
        self.nodes.append(node)
        return node

    def add_edge(self, src: str, dst: str, **kw) -> "GraphEdge":
        edge = GraphEdge(src=src, dst=dst, **kw)
        self.edges.append(edge)
        return edge

    def node_ids(self) -> set:
        return {n.id for n in self.nodes}

    def find_node(self, nid: str) -> Optional[GraphNode]:
        for n in self.nodes:
            if n.id == nid:
                return n
        return None

    def highlight(self, ids: set) -> None:
        """将给定节点（及以之开头的边）标记为 active。"""
        idset = set(ids)
        for n in self.nodes:
            if n.id in idset:
                n.active = True
        for e in self.edges:
            if e.src in idset or e.dst in idset:
                e.active = True


# ==========================================================
# 跨引擎事件
# ==========================================================
@dataclass
class EngineEvent:
    """引擎单次行为产生的事件，供 Orchestrator 订阅。"""
    engine: str                       # 引擎实例名
    etype: str                       # enter | tick | fired | step | decide | change
    payload: Dict[str, Any] = field(default_factory=dict)


# ==========================================================
# 统一引擎契约（Protocol）
# ==========================================================
@runtime_checkable
class Engine(Protocol):
    name: str
    kind: str

    def load(self, spec: Dict[str, Any]) -> None: ...
    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult: ...
    def reset(self) -> None: ...
    def summary(self) -> str: ...
    def visualize(self, highlight: Optional[set] = None) -> Graph: ...


# ==========================================================
# 基础适配器：把「公共字段 + on_event」塞进各范式
# ==========================================================
class BaseAdapter:
    """所有适配器的公共父类，提供 name/kind/事件总线。"""

    kind: str = "base"

    def __init__(self, name: str = "", on_event=None):
        self.name = name
        self._on_event = on_event

    def _emit(self, etype: str, **payload) -> None:
        if callable(self._on_event):
            self._on_event(EngineEvent(engine=self.name, etype=etype,
                                       payload=payload))

    # 子类按需覆写
    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec

    def reset(self) -> None:
        self.load(getattr(self, "spec", {}))

    def summary(self) -> str:
        return f"[{self.kind}] {self.name}"

    def visualize(self, highlight=None) -> Graph:
        return Graph(kind=self.kind, title=self.name)
