# -*- coding: utf-8 -*-
"""
马尔可夫链（Markov Chain）—— 概率状态机
=======================================

马尔可夫链是「状态 + 转移概率」的随机模型，满足**马尔可夫性质**：
下一步状态只取决于当前状态，与历史无关（无记忆性）。

离散时间马尔可夫链（DTMC）由以下要素定义：
  * 状态空间 S = {s₁, s₂, ...}
  * 转移概率矩阵 P：P(i, j) = Pr(X_{t+1}=s_j | X_t=s_i)
  * 初始分布 / 初始状态

工程价值（相对确定性 FSM 的增强）
---------------------------------
* 刻画**不确定 / 随机**演化：网络抖动、用户行为、天气、市场等。
* 可计算**稳态分布 π**（πP = π，即长期占比），用于容量规划、负载预测。
* 可模拟路径，做蒙特卡洛仿真。

稳态求解：本模块用**幂迭代（power iteration）** π ← πP 直至收敛；
对可约链给出吸收态提示。

数据驱动：build_markov_chain(spec) 由 config.json 的 markov_chains 段构造。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional


class MarkovChain:
    def __init__(self, states: List[str],
                 matrix: Dict[str, Dict[str, float]],
                 initial: Optional[str] = None,
                 seed: Optional[int] = None):
        self.states = list(states)
        self.index = {s: i for i, s in enumerate(self.states)}
        if initial is None:
            initial = self.states[0]
        if initial not in self.states:
            raise ValueError(f"初始状态不在状态空间: {initial}")
        self.initial = initial
        self.current = initial
        self.rng = random.Random(seed)

        # 规整化矩阵：每行概率和应为 1（容错：自动归一化）
        self.matrix: List[List[float]] = []
        for s in self.states:
            row = matrix.get(s, {})
            dist = [float(row.get(t, 0.0)) for t in self.states]
            total = sum(dist)
            if total <= 0:
                # 退化：停留在原地
                dist = [1.0 if t == s else 0.0 for t in self.states]
            else:
                dist = [d / total for d in dist]
            self.matrix.append(dist)

    # ---------- 单步 ----------
    def step(self, state: Optional[str] = None) -> str:
        """根据当前（或给定）状态采样下一状态。"""
        s = state or self.current
        i = self.index[s]
        r = self.rng.random()
        acc = 0.0
        for j, p in enumerate(self.matrix[i]):
            acc += p
            if r <= acc:
                self.current = self.states[j]
                return self.current
        self.current = self.states[-1]
        return self.current

    def simulate(self, steps: int = 20, start: Optional[str] = None) -> List[str]:
        """蒙特卡洛仿真，返回状态序列（含起点）。"""
        seq = [start or self.current]
        cur = start or self.current
        for _ in range(steps):
            cur = self.step(cur)
            seq.append(cur)
        return seq

    # ---------- 稳态 ----------
    def steady_state(self, max_iter: int = 2000, tol: float = 1e-9
                     ) -> Dict[str, float]:
        """幂迭代求稳态分布 π（πP = π）。"""
        n = len(self.states)
        pi = [1.0 / n] * n
        for _ in range(max_iter):
            new = [0.0] * n
            for j in range(n):
                s = 0.0
                for i in range(n):
                    s += pi[i] * self.matrix[i][j]
                new[j] = s
            diff = sum(abs(new[k] - pi[k]) for k in range(n))
            pi = new
            if diff < tol:
                break
        return {self.states[i]: pi[i] for i in range(n)}

    def is_absorbing(self, state: str) -> bool:
        i = self.index[state]
        return self.matrix[i][i] >= 1.0 - 1e-9

    # ---------- 展示 ----------
    def show_matrix(self) -> str:
        header = "       " + "".join(f"{s:>8}" for s in self.states)
        lines = [header]
        for s, row in zip(self.states, self.matrix):
            lines.append(f"{s:>7}" + "".join(f"{p:>8.2f}" for p in row))
        return "\n".join(lines)

    def __repr__(self):
        return (f"<MarkovChain states={self.states} "
                f"current={self.current}>")


def build_markov_chain(spec: Dict[str, Any]) -> MarkovChain:
    """由声明式规格构造 MarkovChain。

    spec 形如：
        {
          "name": "天气模型",
          "states": ["晴", "阴", "雨"],
          "matrix": {
            "晴": {"晴": 0.6, "阴": 0.3, "雨": 0.1},
            "阴": {"晴": 0.3, "阴": 0.4, "雨": 0.3},
            "雨": {"晴": 0.2, "阴": 0.3, "雨": 0.5}
          },
          "initial": "晴"
        }
    """
    return MarkovChain(
        states=spec["states"],
        matrix=spec["matrix"],
        initial=spec.get("initial"),
    )
