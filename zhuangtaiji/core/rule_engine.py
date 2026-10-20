# -*- coding: utf-8 -*-
"""
规则引擎（Rule Engine）—— RETE 风格正向推理
============================================

规则引擎源自「基于规则的专家系统」。本模块实现经典的 **RETE 算法**（Charles
Forgy, 1979）的轻量版，用于**正向链式推理（forward chaining）**：

  事实 (Working Memory)  →  α 网络(单事实过滤)  →  β 网络(多模式连接/Join)
     →  冲突集 Agenda  →  冲突消解  →  触发规则 RHS(断言/撤销事实)  →  循环

组成（参考 cnblogs Rete 系列讲义 / Drools 文档）：
* WME / Fact（工作记忆元素）：带类型的属性集合，如
  Fact("order", {user:"u1", status:"paid"})。
* Production（产生式）：LHS（when 一组 Pattern 条件）+ RHS（then 一组动作）。
* α 网络：每个 Pattern 对事实做单事实匹配，缓存到 α-memory，避免每轮全表扫描。
* β 网络：把多个 Pattern 的匹配结果按**共享连接键 (key)** 做相等连接（Join），
  即「订单.user == 用户.user」式关联，得到完整绑定 (binding)。
* Agenda（议程）：所有被激活的产生式进入冲突集，按 priority 做冲突消解后触发。
* RHS 执行 assert / retract 会改变 Working Memory，从而可能激活新规则
  （「动态匹配链」），直至达到不动点（fixpoint）或达到最大迭代。

适用场景
--------
* 风控规则、促销发券、权限推导、告警关联等「IF 多条件 THEN 动作」业务。
* 与 FSM/行为树互补：规则引擎擅长「声明式、数据驱动的关联推理」。

数据驱动：build_rule_engine(spec) 由 config.json 的 rule_engines 段构造。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ==========================================
# 事实
# ==========================================
class Fact:
    _counter = 0

    def __init__(self, type_: str, attrs: Optional[Dict[str, Any]] = None):
        self.type = type_
        self.attrs = dict(attrs or {})
        Fact._counter += 1
        self.fid = Fact._counter

    def get(self, key, default=None):
        return self.attrs.get(key, default)

    def __repr__(self):
        return f"Fact({self.type!r},{self.attrs})"


# ==========================================
# 匹配算子
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
    "truthy": lambda a, b: bool(a),
}


def _test(actual, op, target) -> bool:
    fn = _OPS.get(op, _OPS["eq"])
    try:
        return bool(fn(actual, target))
    except Exception:
        return False


def _satisfies(pattern: Dict[str, Any], fact: Fact) -> bool:
    if pattern.get("type") and fact.type != pattern["type"]:
        return False
    for field_, cond in (pattern.get("constraints") or {}).items():
        actual = fact.get(field_)
        if isinstance(cond, dict) and "op" in cond:
            op, target = cond["op"], cond.get("value")
        else:
            op, target = "eq", cond
        if not _test(actual, op, target):
            return False
    return True


# ==========================================
# 产生式
# ==========================================
@dataclass
class Production:
    name: str
    when: List[Dict[str, Any]]
    then: List[Dict[str, Any]]
    priority: int = 0

    def match_lists(self, facts: List[Fact]) -> List[List[Fact]]:
        return [[f for f in facts if _satisfies(p, f)] for p in self.when]


# ==========================================
# 引擎
# ==========================================
class RuleEngine:
    def __init__(self, name: str = "RuleEngine",
                 facts: Optional[List[Fact]] = None,
                 productions: Optional[List[Production]] = None):
        self.name = name
        self.working_memory: List[Fact] = list(facts or [])
        self.productions: List[Production] = list(productions or [])
        self.fired_log: List[Dict[str, Any]] = []
        self._seq = 0
        # 已触发过的（规则名, 事实ID元组）集合，避免同一绑定重复触发
        self._fired: set = set()

    # ---------- 事实管理 ----------
    def assert_fact(self, type_: str, attrs: Dict[str, Any]) -> Fact:
        f = Fact(type_, attrs)
        self.working_memory.append(f)
        return f

    def retract_fact(self, type_: str, attrs: Optional[Dict[str, Any]] = None) -> int:
        """撤销第一个匹配的事实，返回撤销数量（0/1）。"""
        for i, f in enumerate(self.working_memory):
            if f.type != type_:
                continue
            if attrs and any(f.get(k) != v for k, v in attrs.items()):
                continue
            self.working_memory.pop(i)
            return 1
        return 0

    def reset(self, facts: Optional[List[Fact]] = None) -> None:
        self.working_memory = list(facts or [])
        self.fired_log.clear()
        self._fired.clear()

    # ---------- 激活收集（α + β 匹配） ----------
    def _gen_tokens(self, patterns, matched, idx=0, chosen=None, tokens=None):
        if chosen is None:
            chosen = []
        if tokens is None:
            tokens = []
        if idx == len(patterns):
            tokens.append(list(chosen))
            return tokens
        for f in matched[idx]:
            ok = f.fid not in [c.fid for c in chosen]
            if ok:
                k = patterns[idx].get("key")
                for prev_f, prev_p in zip(chosen, patterns[:idx]):
                    pk = prev_p.get("key")
                    if pk and pk == k and prev_f.get(pk) != f.get(pk):
                        ok = False
                        break
            if ok:
                self._gen_tokens(patterns, matched, idx + 1, chosen + [f], tokens)
        return tokens

    def _bindings(self, patterns, token) -> Dict[str, Any]:
        b: Dict[str, Any] = {}
        for p, f in zip(patterns, token):
            k = p.get("key")
            if k:
                b[k] = f.get(k)
        return b

    def _collect_activations(self) -> List[Tuple[Production, Dict[str, Any], tuple]]:
        acts = []
        for prod in self.productions:
            matched = prod.match_lists(self.working_memory)
            if any(len(m) == 0 for m in matched):
                continue
            tokens = self._gen_tokens(prod.when, matched)
            for tok in tokens:
                key = (prod.name, tuple(f.fid for f in tok))
                if key in self._fired:        # 同一绑定已触发过，跳过
                    continue
                binds = self._bindings(prod.when, tok)
                acts.append((prod, binds, tuple(f.fid for f in tok)))
        return acts

    # ---------- 变量替换 ----------
    @staticmethod
    def _subst(value, binds):
        if isinstance(value, str) and value.startswith("$"):
            return binds.get(value[1:], value)
        return value

    def _fire(self, prod: Production, binds: Dict[str, Any]) -> None:
        for eff in prod.then:
            if "assert" in eff:
                spec = {k: self._subst(v, binds) for k, v in eff["assert"].items()}
                t = spec.pop("type", "fact")
                self.assert_fact(t, spec)
            elif "retract" in eff:
                spec = eff["retract"]
                attrs = {k: self._subst(v, binds)
                         for k, v in spec.items() if k != "type"}
                self.retract_fact(spec.get("type", ""), attrs or None)
            elif "log" in eff:
                msg = self._subst(eff["log"], binds)
                self.fired_log.append({"rule": prod.name, "type": "log",
                                       "msg": str(msg)})
        self._seq += 1
        self.fired_log.append({
            "rule": prod.name, "type": "fire", "bindings": dict(binds),
            "seq": self._seq,
        })

    # ---------- 主循环 ----------
    def forward_chain(self, max_iter: int = 100) -> List[Dict[str, Any]]:
        """正向链式推理，直到无激活或达到 max_iter。返回触发日志。"""
        for _ in range(max_iter):
            acts = self._collect_activations()
            if not acts:
                break
            # 冲突消解：priority 高者优先，其次触发序号
            acts.sort(key=lambda a: -a[0].priority)
            prod, binds, tok = acts[0]
            self._fired.add((prod.name, tok))
            self._fire(prod, binds)
        return self.fired_log

    # ---------- 展示 ----------
    def facts_summary(self) -> str:
        return "\n".join(f"  • {f}" for f in self.working_memory) or "  (空)"

    def __repr__(self):
        return (f"<RuleEngine {self.name!r} facts={len(self.working_memory)} "
                f"rules={len(self.productions)}>")


# ==========================================
# 声明式构建
# ==========================================
def build_production(spec: Dict[str, Any]) -> Production:
    return Production(
        name=spec.get("name", "rule"),
        when=spec.get("when", []),
        then=spec.get("then", []),
        priority=int(spec.get("priority", 0)),
    )


def build_rule_engine(spec: Dict[str, Any]) -> RuleEngine:
    """由声明式规格构造 RuleEngine。

    spec 形如：
        {
          "name": "电商促销",
          "initial_facts": [
            {"type": "order", "user": "u1", "status": "paid", "amount": 800},
            {"type": "user",  "user": "u1", "vip": true}
          ],
          "rules": [
            {
              "name": "VIP大额发券",
              "priority": 10,
              "when": [
                {"type": "order", "key": "user", "constraints": {"status": "paid", "amount": {"op": "gt", "value": 500}}},
                {"type": "user",  "key": "user", "constraints": {"vip": true}}
              ],
              "then": [
                {"assert": {"type": "coupon", "user": "$user", "level": "gold", "value": 100}},
                {"log": "向 $user 发放黄金券"}
              ]
            }
          ]
        }
    """
    facts = [Fact(f["type"], {k: v for k, v in f.items() if k != "type"})
             for f in spec.get("initial_facts", [])]
    prods = [build_production(r) for r in spec.get("rules", [])]
    return RuleEngine(name=spec.get("name", "RuleEngine"),
                      facts=facts, productions=prods)
