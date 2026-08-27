# -*- coding: utf-8 -*-
"""
图形化渲染层（P0-2）
====================

把 ``engine_base.Graph`` 渲染为三种形式：

* ``to_mermaid(graph)`` —— Mermaid 文本（可贴到 GitHub / Mermaid Live 渲染）。
* ``to_dot(graph)``     —— Graphviz DOT 文本（离线可用 ``dot -Tpng`` 出图）。
* ``to_ascii(graph)``   —— Unicode 字符图（**无需任何外部依赖**，tkinter 文本控件直接显示）。

这是「告别文本日志、图形化看状态机/行为树/决策树/Petri 网」的核心。
``active`` 标记会渲染为高亮（ASCII 用 ▶/◆，Mermaid/DOT 用样式 class）。
"""
from __future__ import annotations

from typing import Dict, List

from .engine_base import Graph, GraphNode


# ---------- 通用：节点形状 -> 字符 ----------
_SHAPE_BOX = "■"
_SHAPE_CIRCLE = "○"
_SHAPE_RECT = "▢"
_SHAPE_DIAMOND = "◆"
_SHAPE_ROUND = "⬢"

_SHAPE_CHARS = {
    "box": _SHAPE_BOX,
    "circle": _SHAPE_CIRCLE,
    "rect": _SHAPE_RECT,
    "diamond": _SHAPE_DIAMOND,
    "round": _SHAPE_ROUND,
}


def _node_char(n: GraphNode) -> str:
    ch = _SHAPE_CHARS.get(n.shape, _SHAPE_BOX)
    return f"▶{ch}" if n.active else ch


def _safe_label(s: str) -> str:
    return (s or "").replace("\n", " ").strip()[:40]


# ==========================================================
# ASCII（离线安全，默认渲染）
# ==========================================================
def to_ascii(g: Graph, max_w: int = 60) -> str:
    lines: List[str] = []
    if g.title:
        lines.append(f"╔═ {g.title} ══")
    # 节点
    lines.append(f"── 节点 ({len(g.nodes)}) ──")
    for n in g.nodes:
        mark = "●" if n.active else " "
        lines.append(f" {mark} {_node_char(n)} {n.id}: {_safe_label(n.label)}")
    # 边
    if g.edges:
        lines.append(f"── 转移/边 ({len(g.edges)}) ──")
        for e in g.edges:
            arrow = "─>>" if e.active else "-->"
            lbl = f" :{e.label}" if e.label else ""
            lines.append(f"    {e.src} {arrow} {e.dst}{lbl}")
    return "\n".join(lines)


# ==========================================================
# Mermaid
# ==========================================================
def to_mermaid(g: Graph) -> str:
    parts: List[str] = []
    header = "stateDiagram-v2" if g.kind == "stateDiagram" else f"flowchart {g.direction}"
    parts.append(header)
    if g.title:
        parts.append(f"    title {g.title}")

    # 子图（嵌套状态机）
    for sg_id, node_ids in g.subgraphs.items():
        parts.append(f"    subgraph {sg_id}")
        for nid in node_ids:
            n = g.find_node(nid)
            if n:
                parts.append(f"        {_m_node(n)}")
        parts.append("    end")

    # 节点（非子图内的）
    sg_all = {i for ids in g.subgraphs.values() for i in ids}
    for n in g.nodes:
        if n.id in sg_all:
            continue
        parts.append("    " + _m_node(n))

    # 边
    for e in g.edges:
        style = " -.->" if e.style == "dotted" else "-->"
        lbl = f"|{e.label}|" if e.label else ""
        cls = ":::active" if e.active else ""
        parts.append(f"    {e.src} {style}{lbl} {e.dst}{cls}")
    if g.kind != "stateDiagram":
        parts.append("    classDef active fill:#FFF3A0,stroke:#E65100,stroke-width:3px;")
    return "\n".join(parts)


def _m_node(n: GraphNode) -> str:
    cls = ":::active" if n.active else ""
    if n.shape == "circle":
        return f"{n.id}[((\"{_safe_label(n.label)}\"))]{cls}"
    if n.shape == "diamond":
        return f"{n.id}{{{_safe_label(n.label)}}}{cls}"
    if n.shape == "round":
        return f"{n.id}({_safe_label(n.label)}){cls}"
    return f"{n.id}[{_safe_label(n.label)}]{cls}"


# ==========================================================
# Graphviz DOT
# ==========================================================
def to_dot(g: Graph) -> str:
    lines: List[str] = ["digraph G {"]
    lines.append(f'  rankdir={_dot_dir(g.direction)};')
    if g.title:
        lines.append(f'  label={_dot_q(g.title)};')
    shape_map = {
        "box": "box", "circle": "circle", "rect": "rect",
        "diamond": "diamond", "round": "box",
    }
    for n in g.nodes:
        style = 'color="#E65100",penwidth=3,style=filled,fillcolor="#FFF3A0"' if n.active else ""
        lines.append(f'  "{n.id}" [label={_dot_q(_safe_label(n.label))} '
                     f'shape={shape_map.get(n.shape, "box")} {style}];')
    for e in g.edges:
        style = 'color="#E65100",penwidth=3' if e.active else ""
        lbl = f'label={_dot_q(e.label)},' if e.label else ""
        lines.append(f'  "{e.src}" -> "{e.dst}" [{lbl}{style}];')
    lines.append("}")
    return "\n".join(lines)


def _dot_dir(d: str) -> str:
    return {"TB": "TB", "LR": "LR", "BT": "BT", "RL": "RL"}.get(d, "TB")


def _dot_q(s: str) -> str:
    return '"' + str(s).replace('"', "'") + '"'


# ==========================================================
# 便捷：根据可用性选择最佳渲染
# ==========================================================
def render(graph: Graph, fmt: str = "ascii") -> str:
    fmt = (fmt or "ascii").lower()
    if fmt == "mermaid":
        return to_mermaid(graph)
    if fmt == "dot":
        return to_dot(graph)
    return to_ascii(graph)
