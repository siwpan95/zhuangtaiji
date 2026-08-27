# -*- coding: utf-8 -*-
"""
决策树（Decision Tree）路由引擎
================================

与「机器学习决策树」（用数据训练出分类模型）不同，本模块实现的是
**规则型 / 启发式决策树**：以声明方式描述「按特征做判断、沿分支路由」的逻辑，
常用于业务分流、策略选择、配置 routing 等场景。

与状态机 / 行为树的关系
-----------------------
* 状态机：强调「状态 + 转移事件」的时序演化。
* 行为树：强调「每帧重新评估」的响应式行为编排。
* 决策树：强调「一次性的、基于特征空间的路由决策」——给定一组输入特征，
  沿 if/else 分支走到叶子，得到结论（类别 / 动作 / 值）。

节点类型
--------
* condition : 对特征做比较（op: eq/ne/gt/lt/ge/le/in/contains/exists），
              满足则走 true_child，否则走 false_child。
* switch    : 对特征取值做多路匹配（case -> 子节点），默认走 default_child。
* action    : 叶子节点，产生结论（label / value / payload）。

所有比较都基于一个「特征字典」(features)，由调用方注入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union


# ==========================================
# 节点基类
# ==========================================
class DTNode:
    def __init__(self, name: str = ""):
        self.name = name or self.__class__.__name__

    def evaluate(self, features: Dict[str, Any]) -> "DTNode":
        raise NotImplementedError

    def walk_path(self, features: Dict[str, Any]) -> List[str]:
        """返回从根到命中节点的名称路径（用于可视化 / 审计）。"""
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name!r}>"


# ==========================================
# 叶子：动作 / 结论
# ==========================================
@dataclass
class DecisionResult:
    label: str = ""                 # 结论标签（类别）
    value: Any = None               # 结论值
    payload: Dict[str, Any] = field(default_factory=dict)  # 附加信息
    path: List[str] = field(default_factory=list)          # 命中路径


class ActionNode(DTNode):
    def __init__(self, name: str = "", result: Optional[DecisionResult] = None,
                 label: str = "", value: Any = None,
                 payload: Optional[Dict[str, Any]] = None):
        super().__init__(name)
        self.result = result or DecisionResult(label=label, value=value,
                                               payload=payload or {})

    def evaluate(self, features):
        return self

    def walk_path(self, features):
        return [self.name]


# ==========================================
# 条件节点
# ==========================================
_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "ge": lambda a, b: a >= b,
    "le": lambda a, b: a <= b,
    "in": lambda a, b: a in (b or []),
    "not_in": lambda a, b: a not in (b or []),
    "contains": lambda a, b: b in a if isinstance(a, (list, str, tuple, set)) else False,
    "exists": lambda a, b: a is not None,
    "not_exists": lambda a, b: a is None,
    "truthy": lambda a, b: bool(a),
}


class ConditionNode(DTNode):
    def __init__(self, name: str = "", key: str = "", op: str = "exists",
                 value: Any = None,
                 true_child: Optional[DTNode] = None,
                 false_child: Optional[DTNode] = None):
        super().__init__(name)
        self.key = key
        self.op = op
        self.value = value
        self.true_child = true_child
        self.false_child = false_child

    def _test(self, features) -> bool:
        actual = features.get(self.key)
        fn = _OPS.get(self.op, _OPS["exists"])
        try:
            return bool(fn(actual, self.value))
        except Exception:
            return False

    def evaluate(self, features):
        branch = self.true_child if self._test(features) else self.false_child
        if branch is None:
            return self
        return branch.evaluate(features)

    def walk_path(self, features):
        ok = self._test(features)
        branch = self.true_child if ok else self.false_child
        if branch is None:
            return [f"{self.name}?{('T' if ok else 'F')}"]
        return [f"{self.name}?{('T' if ok else 'F')}"] + branch.walk_path(features)


# ==========================================
# 多路分支节点
# ==========================================
class SwitchNode(DTNode):
    def __init__(self, name: str = "", key: str = "",
                 cases: Optional[Dict[Any, DTNode]] = None,
                 default_child: Optional[DTNode] = None):
        super().__init__(name)
        self.key = key
        self.cases = dict(cases or {})
        self.default_child = default_child

    def evaluate(self, features):
        actual = features.get(self.key)
        child = self.cases.get(actual, self.default_child)
        if child is None:
            return self
        return child.evaluate(features)

    def walk_path(self, features):
        actual = features.get(self.key)
        child = self.cases.get(actual, self.default_child)
        if child is None:
            return [f"{self.name}={actual}?（无匹配）"]
        return [f"{self.name}={actual}"] + child.walk_path(features)


# ==========================================
# 决策树：入口 + 解释
# ==========================================
class DecisionTree:
    def __init__(self, root: DTNode, name: str = "DecisionTree"):
        self.root = root
        self.name = name

    def decide(self, features: Dict[str, Any]) -> DecisionResult:
        """根据特征做一次路由决策，返回结论 + 命中路径。"""
        leaf = self.root.evaluate(features)
        path = self.root.walk_path(features)
        if isinstance(leaf, ActionNode):
            result = DecisionResult(
                label=leaf.result.label,
                value=leaf.result.value,
                payload=dict(leaf.result.payload),
                path=path,
            )
        elif isinstance(leaf, (ConditionNode, SwitchNode)):
            # 落到了条件/分支节点而没有子节点（即该分支未定义结论）
            result = DecisionResult(label="<无结论>", value=None,
                                    payload={"note": "分支未定义结论"},
                                    path=path)
        else:
            result = DecisionResult(label=str(leaf.name), path=path)
        return result


# ==========================================
# 数据驱动构造（声明式）
# ==========================================
def build_node(spec: Dict[str, Any]) -> DTNode:
    ntype = spec.get("type", "action")
    name = spec.get("name", ntype)

    if ntype == "condition":
        return ConditionNode(
            name=name,
            key=spec.get("key", ""),
            op=spec.get("op", "exists"),
            value=spec.get("value"),
            true_child=build_node(spec["true"]) if spec.get("true") else None,
            false_child=build_node(spec["false"]) if spec.get("false") else None,
        )

    if ntype == "switch":
        cases = {}
        for case_key, child_spec in (spec.get("cases") or {}).items():
            cases[case_key] = build_node(child_spec)
        default_child = build_node(spec["default"]) if spec.get("default") else None
        return SwitchNode(name=name, key=spec.get("key", ""),
                          cases=cases, default_child=default_child)

    if ntype == "action":
        return ActionNode(
            name=name,
            label=spec.get("label", name),
            value=spec.get("value"),
            payload=spec.get("payload", {}),
        )

    raise ValueError(f"未知决策树节点类型: {ntype}")


def build_decision_tree(spec: Dict[str, Any]) -> DecisionTree:
    """由声明式规格构造 DecisionTree。

    spec 形如：
        {
          "name": "负载路由",
          "root": { "type": "condition", "key": "load", "op": "gt", "value": 80,
                    "true":  { "type": "action", "label": "扩容" },
                    "false": { "type": "action", "label": "维持" } }
        }
    """
    root_spec = spec.get("root")
    if not root_spec:
        raise ValueError("决策树规格缺少 root")
    return DecisionTree(build_node(root_spec), name=spec.get("name", "DecisionTree"))
