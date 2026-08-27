# -*- coding: utf-8 -*-
"""
LLM Agent 插件（P2-2）
=====================

把 LLM 作为「控制器 / 动作节点」接入决策引擎，但带**安全护栏**：
LLM 只能从「声明允许的合法事件集合」中选择下一步动作，绝不能直接触发
任意状态转移——由机器负责校验与执行。

* 后端可插拔：``LocalBackend``（默认，确定性 stub，离线可跑）/
  ``OpenAIBackend``（设置环境变量 LLM_API_KEY 后可选启用，失败自动回退本地）。
* 这正是 statelyai/agent「用 schema 约束 LLM 输出」思路的轻量实现。

依赖：仅标准库；OpenAI 后端为惰性导入，未安装/未配置时完全不影响离线运行。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Protocol, Set

from ..engine_base import BaseAdapter, EngineResult, Graph
from ..plugin import EnginePlugin


# ==========================================================
# 后端协议
# ==========================================================
class LLMBackend(Protocol):
    name: str
    def choose(self, prompt: str, legal_events: List[str]) -> Optional[str]: ...


class LocalBackend:
    """离线确定性后端：按上下文做简单启发式选择（无需联网）。"""
    name = "local"

    def choose(self, prompt: str, legal_events: List[str]) -> Optional[str]:
        if not legal_events:
            return None
        # 启发式：若 prompt 提示「完成 / 已达终点」则优先选 complete；
        # 否则轮询返回首个合法事件（确定性、可复现）。
        if "finished" in prompt or "完成" in prompt:
            for e in legal_events:
                if e in ("complete", "finish"):
                    return e
        return legal_events[0]


class OpenAIBackend:
    """可选云端后端：惰性导入 openai，仅在配置 LLM_API_KEY 时启用。"""
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self._client = None

    def _lazy(self):
        if self._client is None:
            try:
                from openai import OpenAI  # 惰性，避免强制依赖
                self._client = OpenAI(api_key=os.environ.get("LLM_API_KEY"))
            except Exception:
                self._client = False
        return self._client

    def choose(self, prompt: str, legal_events: List[str]) -> Optional[str]:
        client = self._lazy()
        if not client:
            return None
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content":
                     "你是一个受限决策控制器。只能从给定的合法事件列表中"
                     "选择一个最合适的返回，只输出事件名本身。"},
                    {"role": "user", "content":
                     f"{prompt}\n合法事件: {legal_events}"},
                ],
                temperature=0.2,
            )
            txt = resp.choices[0].message.content.strip().strip("`\"' ")
            for e in legal_events:
                if e == txt or txt.endswith(e):
                    return e
        except Exception:
            pass
        return None


# ==========================================================
# 引擎
# ==========================================================
class LLMAgentEngine(BaseAdapter):
    kind = "llm_agent"

    def load(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.goal = spec.get("goal", "")
        self.legal_events = list(spec.get("legal_events", []))
        backend = spec.get("backend", "local")
        if backend == "openai" and os.environ.get("LLM_API_KEY"):
            self.backend: LLMBackend = OpenAIBackend()
        else:
            self.backend = LocalBackend()
        self.last_event: Optional[str] = None
        self._counter = 0

    def step(self, ctx: Optional[Dict[str, Any]] = None) -> EngineResult:
        ctx = ctx or {}
        legal = ctx.get("legal_events") or self.legal_events
        state = ctx.get("state", "")
        prompt = f"目标: {self.goal}\n当前状态: {state}"
        # 安全护栏：后端返回的事件若不在合法集合，则拒绝并回退本地选择
        event = self.backend.choose(prompt, legal)
        if event not in legal:
            event = LocalBackend().choose(prompt, legal)
        self.last_event = event
        self._counter += 1
        self._emit("decide", event=event, backend=self.backend.name)
        return EngineResult(
            kind="event", value=event,
            detail={"legal": legal, "backend": self.backend.name,
                    "state": state},
        )

    def summary(self) -> str:
        return (f"目标: {self.goal}\n后端: {self.backend.name}\n"
                f"合法事件: {self.legal_events}\n最近选择: {self.last_event}")

    def visualize(self, highlight: Optional[Set[str]] = None) -> Graph:
        g = Graph(kind="flowchart", direction="LR", title=f"LLM 控制器 {self.name}")
        g.add_node("LLM", "LLM 控制器", shape="round")
        for e in self.legal_events:
            g.add_node(f"E_{e}", e, shape="rect", active=(e == self.last_event))
            g.add_edge("LLM", f"E_{e}")
        return g


PLUGIN = EnginePlugin(
    kind="llm_agent",
    label="LLM Agent (插件 · 离线可跑)",
    description="LLM 作受限控制器：仅能触发声明合法事件（安全护栏）",
    engine_cls=LLMAgentEngine,
    specs_provider=lambda: __import__("core.config", fromlist=["load_config"])
        .load_config().get("llm_agents", {}),
)
