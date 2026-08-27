# -*- coding: utf-8 -*-
"""
决策表（Decision Table）范式插件
================================

一个全新的、独立于内置 7 范式的「决策表」引擎，用于证明插件扩展点：
只需在本目录放一个文件、暴露 ``PLUGIN``，无需改动 ``core`` 任何代码，
即可被工作台自动发现并生成 Tab。

决策表 = 一组「条件 → 结论」规则，按声明顺序匹配（首条命中即返回），
适合「多条件组合路由」这类比决策树更表格化、更易审阅的场景。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ..engine_base import BaseAdapter, EngineResult, Graph
from ..plugin import EnginePlugin


_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "ge": lambda a, b: a >= b,
    "le": lambda a, b: a <= b,
    "in": lambda a, b: a in (b or []),
    "truthy": lambda a, b: bool(a),
}


class DecisionTableEngine(BaseAdapter):
    kind = "decision_table"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.rules = spec.get("rules", [])
        self.else_result = spec.get("else", "<无匹配>")
        self.last_match: Optional[str] = None

    def _match(self, cond: Dict[str, Any], features: Dict[str, Any]) -> bool:
        for key, expr in cond.items():
            actual = features.get(key)
            if isinstance(expr, dict) and "op" in expr:
                op = expr["op"]
                target = expr.get("value")
            else:
                op, target = "eq", expr
            fn = _OPS.get(op, _OPS["eq"])
            try:
                if not fn(actual, target):
                    return False
            except Exception:
                return False
        return True

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        features = ctx or {}
        matched_idx = None
        matched_result = self.else_result
        for i, rule in enumerate(self.rules):
            if self._match(rule.get("conditions", {}), features):
                matched_idx = i
                matched_result = rule.get("result", self.else_result)
                break
        self.last_match = f"R{matched_idx}" if matched_idx is not None else None
        self._emit("decide", result=matched_result, rule=matched_idx)
        return EngineResult(
            kind="decision", value=matched_result,
            detail={"rule_index": matched_idx,
                    "matched_rule": self.rules[matched_idx] if matched_idx is not None else None},
        )

    def summary(self) -> str:
        return (f"规则数: {len(self.rules)}\n"
                f"最近命中: {self.last_match or '（无/else）'} -> {self.else_result if self.last_match is None else ''}")

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="flowchart", direction="TB", title=f"决策表 {self.name}")
        g.add_node("START", "输入特征", shape="round")
        for i, rule in enumerate(self.rules):
            rid = f"R{i}"
            cond = " & ".join(f"{k}{v}" for k, v in rule.get("conditions", {}).items())
            g.add_node(rid, f"R{i}: {cond}", shape="diamond",
                       active=(rid == self.last_match))
            g.add_edge("START", rid)
            g.add_edge(rid, f"OUT_{i}", label="→ " + str(rule.get("result", "")))
        g.add_node("ELSE", "else", shape="diamond",
                   active=(self.last_match is None))
        g.add_edge("START", "ELSE")
        g.add_edge("ELSE", "OUT_ELSE", label="→ " + str(self.else_result))
        return g


# 插件注册对象（被 PluginRegistry.discover 自动加载）
PLUGIN = EnginePlugin(
    kind="decision_table",
    label="决策表 (插件示例)",
    description="条件→结论规则表，按序首条命中；证明插件扩展点",
    engine_cls=DecisionTableEngine,
    specs_provider=lambda: __import__("core.config", fromlist=["load_config"])
        .load_config().get("decision_tables", {}),
)
