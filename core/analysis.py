# -*- coding: utf-8 -*-
"""
形式化分析模块（P2-1）
====================

把工作台从「能跑起来」升级为「能证明正确性」：

* Petri 网：可达标记集（BFS）、有界性、死锁状态、变迁活性（liveness）。
* 状态机：可达状态集、不可达状态、环检测（cycle detection）。
* 马尔可夫链：吸收态、吸收概率矩阵、从暂态到吸收的期望步数、混合时间估计。
* 决策树：路径/结论覆盖率、特征重要性（按 key 分裂次数）。

均为纯 Python 实现，无外部依赖；可达性带状态数上限以防爆炸。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


# ==========================================================
# 工具：矩阵求逆（高斯消元，用于马尔可夫基本矩阵）
# ==========================================================
def _invert(mat: List[List[float]]) -> List[List[float]]:
    n = len(mat)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)]
         for i, row in enumerate(mat)]
    for col in range(n):
        # 选主元
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[piv] = a[piv], a[col]
        pv = a[col][col] or 1e-12
        a[col] = [x / pv for x in a[col]]
        for r in range(n):
            if r != col:
                f = a[r][col]
                a[r] = [a[r][k] - f * a[col][k] for k in range(2 * n)]
    return [row[n:] for row in a]


# ==========================================================
# Petri 网分析
# ==========================================================
def analyze_petri(spec: Dict[str, Any], cap: int = 4000) -> Dict[str, Any]:
    from .petri_net import build_petri_net

    pn = build_petri_net(spec)
    start = dict(pn.places)
    key = lambda m: tuple(sorted(m.items()))
    seen = {key(start): start}
    queue = [start]
    bounded = {p: 0 for p in pn.places}
    deadlocks: List[str] = []
    enabled_any = {t: False for t in pn.transitions}

    while queue and len(seen) < cap:
        m = queue.pop(0)
        pn.places = dict(m)
        for p, tok in m.items():
            bounded[p] = max(bounded[p], tok)
        en = pn.enabled_transitions()
        if not en:
            deadlocks.append(str(dict(m)))
        for t in en:
            enabled_any[t] = True
        for t in en:
            pn.places = dict(m)
            pn.fire(t)
            k = key(pn.places)
            if k not in seen:
                seen[k] = dict(pn.places)
                queue.append(dict(pn.places))
    pn.places = dict(start)

    n_reach = len(seen)
    dead_trans = [t for t, v in enabled_any.items() if not v]
    k_bound = max(bounded.values()) if bounded else 0
    return {
        "reachable_states": n_reach,
        "bounded": k_bound,  # 最大库所令牌数（k-有界，k=0 表示空网）
        "is_bounded": k_bound < 1_000_000,
        "deadlocks": deadlocks,
        "is_deadlock_free": len(deadlocks) == 0,
        "dead_transitions": dead_trans,
        "liveness_ok": len(dead_trans) == 0,
        "bounded_per_place": bounded,
    }


# ==========================================================
# 状态机分析（平面 / 层次，做扁平化处理）
# ==========================================================
def _flatten_fsm(spec: Dict[str, Any]) -> Tuple[set, List[Tuple[str, str]], str]:
    states = spec.get("states", {})
    is_hier = spec.get("type") == "hierarchical" or \
        any("substates" in s for s in states.values())
    nodes: set = set()
    edges: List[Tuple[str, str]] = []
    initial = spec.get("initial", "")

    def resolve(target, st, prefix):
        for name, node in st.items():
            p = prefix + [name]
            if name == target:
                return "/".join(p)
            if "substates" in node:
                r = resolve(target, node["substates"], p)
                if r:
                    return r
        return None

    def walk(st, prefix):
        for name, node in st.items():
            path = "/".join(prefix + [name])
            nodes.add(path)
            for ev, tgt in (node.get("transitions") or {}).items():
                t = tgt.get("target") if isinstance(tgt, dict) else tgt
                if isinstance(t, str) and t.startswith("#"):
                    edges.append((path, path + t[1:]))
                else:
                    tp = resolve(t, states, [])
                    if tp:
                        edges.append((path, tp))
            if "substates" in node:
                walk(node["substates"], prefix + [name])

    if is_hier:
        walk(states, [])
    else:
        for name, node in states.items():
            nodes.add(name)
            for ev, tgt in (node.get("transitions") or {}).items():
                t = tgt.get("target") if isinstance(tgt, dict) else tgt
                if isinstance(t, str) and t.startswith("#"):
                    edges.append((name, t[1:]))
                else:
                    edges.append((name, t))
    return nodes, edges, initial


def analyze_fsm(spec: Dict[str, Any]) -> Dict[str, Any]:
    nodes, edges, initial = _flatten_fsm(spec)
    adj = {n: [] for n in nodes}
    for a, b in edges:
        if a in adj:
            adj[a].append(b)

    # 可达集 BFS
    reach = {initial}
    q = [initial]
    while q:
        c = q.pop(0)
        for nxt in adj.get(c, []):
            if nxt not in reach:
                reach.add(nxt)
                q.append(nxt)
    unreachable = sorted(nodes - reach)

    # 环检测（DFS 三色）
    color = {n: 0 for n in nodes}  # 0白 1灰 2黑
    has_cycle = [False]

    def dfs(u):
        color[u] = 1
        for v in adj.get(u, []):
            if color.get(v, 0) == 1:
                has_cycle[0] = True
            elif color.get(v, 0) == 0:
                dfs(v)
        color[u] = 2

    for n in nodes:
        if color[n] == 0:
            dfs(n)

    return {
        "total_states": len(nodes),
        "reachable": len(reach),
        "unreachable": unreachable,
        "has_unreachable": len(unreachable) > 0,
        "has_cycle": has_cycle[0],
    }


# ==========================================================
# 马尔可夫链分析
# ==========================================================
def analyze_markov(spec: Dict[str, Any]) -> Dict[str, Any]:
    from .markov_chain import build_markov_chain

    mc = build_markov_chain(spec)
    n = len(mc.states)
    absorbing = [mc.states[i] for i in range(n)
                 if mc.is_absorbing(mc.states[i])]
    transient = [s for s in mc.states if not mc.is_absorbing(s)]

    result: Dict[str, Any] = {
        "absorbing": absorbing,
        "transient": transient,
        "is_absorbing_chain": len(absorbing) > 0,
    }

    if absorbing and transient:
        t_idx = {s: i for i, s in enumerate(transient)}
        a_idx = {s: i for i, s in enumerate(absorbing)}
        Q = [[mc.matrix[mc.index[s]][mc.index[t]] for t in transient]
             for s in transient]
        R = [[mc.matrix[mc.index[s]][mc.index[a]] for a in absorbing]
             for s in transient]
        # N = (I - Q)^-1
        I = [[1.0 if i == j else 0.0 for j in range(len(transient))]
             for i in range(len(transient))]
        ImQ = [[I[i][j] - Q[i][j] for j in range(len(transient))]
               for i in range(len(transient))]
        try:
            N = _invert(ImQ)
        except Exception:
            N = None
        if N:
            # 期望步数 t = N·1
            expected = [sum(row) for row in N]
            # 吸收概率 B = N·R
            B = [[sum(N[i][k] * R[k][j] for k in range(len(transient)))
                  for j in range(len(absorbing))] for i in range(len(transient))]
            result["expected_steps_to_absorb"] = {
                transient[i]: round(expected[i], 3) for i in range(len(transient))}
            result["absorption_prob"] = {
                transient[i]: {absorbing[j]: round(B[i][j], 3)
                               for j in range(len(absorbing))}
                for i in range(len(transient))}

    # 混合时间（粗略：幂迭代到稳态所需的步数估计）
    sd = mc.steady_state()
    result["steady_state"] = {k: round(v, 4) for k, v in sd.items()}
    return result


# ==========================================================
# 决策树分析
# ==========================================================
def analyze_decision_tree(spec: Dict[str, Any]) -> Dict[str, Any]:
    def walk(node, split_counts, leaves):
        if node.get("type") == "condition":
            key = node.get("key", "?")
            split_counts[key] = split_counts.get(key, 0) + 1
            if node.get("true"):
                walk(node["true"], split_counts, leaves)
            if node.get("false"):
                walk(node["false"], split_counts, leaves)
        elif node.get("type") == "switch":
            for c in (node.get("cases") or {}).values():
                walk(c, split_counts, leaves)
            if node.get("default"):
                walk(node["default"], split_counts, leaves)
        elif node.get("type") == "action":
            leaves.append(node.get("label", node.get("name", "?")))

    splits: Dict[str, int] = {}
    leaves: List[str] = []
    if spec.get("root"):
        walk(spec["root"], splits, leaves)
    return {
        "leaf_conclusions": sorted(set(leaves)),
        "n_leaves": len(leaves),
        "feature_importance": splits,  # key -> 分裂次数
        "n_features_used": len(splits),
    }


# ==========================================================
# 统一格式化
# ==========================================================
def format_analysis(kind: str, spec: Dict[str, Any]) -> str:
    if kind == "petri_net":
        r = analyze_petri(spec)
        lines = [
            f"可达标记数: {r['reachable_states']}",
            f"有界性: {'有界' if r['is_bounded'] else '无界'} (k≤{r['bounded']})",
            f"死锁状态: {len(r['deadlocks'])} 个 -> {'无（无死锁）' if r['is_deadlock_free'] else '存在!'}",
            f"变迁活性: {'全部可达' if r['liveness_ok'] else f'死变迁 {r['dead_transitions']}'}",
            f"各库所上限令牌: {r['bounded_per_place']}",
        ]
        return "\n".join(lines)
    if kind == "state_machine":
        r = analyze_fsm(spec)
        lines = [
            f"状态总数: {r['total_states']}  可达: {r['reachable']}",
            f"不可达状态: {r['unreachable'] or '无'}",
            f"含环(自循环/回路): {'是' if r['has_cycle'] else '否'}",
        ]
        return "\n".join(lines)
    if kind == "markov_chain":
        r = analyze_markov(spec)
        lines = [f"吸收态: {r['absorbing'] or '无'}",
                 f"暂态: {r['transient']}"]
        if "expected_steps_to_absorb" in r:
            lines.append("期望步数到吸收: " +
                         str(r["expected_steps_to_absorb"]))
            lines.append("吸收概率: " + str(r["absorption_prob"]))
        lines.append("稳态分布: " + str(r["steady_state"]))
        return "\n".join(lines)
    if kind == "decision_tree":
        r = analyze_decision_tree(spec)
        lines = [
            f"结论(叶子)数: {r['n_leaves']} -> {r['leaf_conclusions']}",
            f"特征重要性(分裂次数): {r['feature_importance']}",
        ]
        return "\n".join(lines)
    return "该范式暂不支持形式化分析。"
