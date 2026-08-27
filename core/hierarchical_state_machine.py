# -*- coding: utf-8 -*-
"""
层次状态机（Hierarchical State Machine, HSM）
============================================

平面有限状态机（FSM）在状态膨胀后会变成「蜘蛛网」般难以维护。HSM 借鉴
UML 状态图（David Harel, 1987）引入层次：一个状态内部可再包含子状态，
从而把复杂逻辑分解为「大状态 → 子状态」的树形结构。

本模块在原有 GenericStateMachine 之上新增：
* 嵌套子状态 (substates)：父状态激活时，其内部有一个「当前子状态」。
* 历史伪状态 (history)：离开复合状态后再返回时，可回到上次的子状态
  （深历史 $ 递归记忆整棵子树 / 浅历史 H 只记直接子）。
* 终态 (final)：子状态机到达 final 后，向上抛出完成事件。
* 内部转移 (internal)：带前缀 "#" 的 target 表示「原地执行动作但不离开状态」，
  因此不触发 on_exit/on_enter。
* 事件冒泡 (bubbling)：当前子状态无法处理的事件，逐级向祖先状态冒泡查找。

配置约定（在 config.json 的 state_machines 中可混用）：
    {
      "type": "hierarchical",        # 标记为层次状态机
      "initial": "power",
      "states": {
        "power": {
          "initial": "off",          # 进入 power 时默认激活 off 子状态
          "history": "shallow",      # 支持浅历史（也可 "deep"）
          "substates": {
            "off":  { "transitions": { "turn_on": "on" } },
            "on":   {
              "initial": "idle",
              "substates": {
                "idle": { "transitions": { "run": "working" } },
                "working": { "transitions": { "stop": "idle", "fault": "error" } },
                "error": { "transitions": { "reset": "#on" } },  # # 内部转移
                "final": {}                                       # 终态
              },
              "transitions": { "power_off": "off" }
            }
          },
          "transitions": { "kill": "off" }
        }
      }
    }
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple


class HierarchicalStateMachine:
    def __init__(self, machine_name: str, full_config: Dict[str, Any],
                 on_action: Optional[Callable] = None):
        config = full_config["state_machines"].get(machine_name)
        if not config:
            raise ValueError(f"找不到状态机配置: {machine_name}")

        self.name = machine_name
        self.config = config
        self.states = config["states"]
        self.on_action = on_action
        self._ctx: Dict[str, Any] = {}  # 最近一次 trigger 的 context（供动作回调）

        # 当前激活路径：从根到叶子，例如 ["power", "on", "idle"]
        self.active_path: List[str] = [config["initial"]]
        self.history: List[Dict[str, Any]] = []  # 路径历史

        # 为每个复合状态记录「最近子状态」（历史）
        self._history_cache: Dict[str, str] = {}
        self._deep_history_cache: Dict[str, List[str]] = {}

        # 进入初始状态（含其默认子状态链）
        self._enter_initial()

    # ---------- 路径工具 ----------
    def _child_node(self, parent: Dict[str, Any], seg: str) -> Dict[str, Any]:
        """在父节点下查找子状态：优先直接键，其次 substates。"""
        if seg in parent:
            return parent[seg]
        return parent["substates"][seg]

    def _node_config(self, path: List[str]) -> Dict[str, Any]:
        node = self.states
        for seg in path:
            node = self._child_node(node, seg)
        return node

    def _is_composite(self, path: List[str]) -> bool:
        return "substates" in self._node_config(path)

    def _leaf_state_id(self) -> str:
        return self.active_path[-1]

    @property
    def current_state_id(self) -> str:
        """对外兼容：返回「全路径 / 叶状态」字符串。"""
        return "/".join(self.active_path)

    @property
    def current_leaf(self) -> str:
        return self.active_path[-1]

    # ---------- 进入 / 退出 ----------
    def _find_path(self, target, node_dict=None, prefix=None):
        """在状态树中查找名为 target 的节点，返回其完整路径。"""
        if node_dict is None:
            node_dict = self.states
            prefix = []
        for name, node in node_dict.items():
            path = prefix + [name]
            if name == target:
                return path
            if "substates" in node:
                res = self._find_path(target, node["substates"], path)
                if res:
                    return res
        return None

    def _enter_node(self, path: List[str]):
        self._invoke("enter", path)
        if len(path) >= 2:
            parent = "/".join(path[:-1])
            self._history_cache[parent] = path[-1]

    def _enter_default_descendants(self, path: List[str]):
        """进入某节点的默认子状态（及其子孙），并维护 active_path。"""
        node = self._node_config(path)
        if "substates" in node and node.get("initial"):
            child_path = path + [node["initial"]]
            self._enter_node(child_path)
            self.active_path = child_path
            self._enter_default_descendants(child_path)

    def _enter_specific_descendants(self, path: List[str], child: str):
        child_path = path + [child]
        self._enter_node(child_path)
        self.active_path = child_path
        self._enter_default_descendants(child_path)

    def _exit_path(self, path: List[str]):
        """从深到浅 exit 给定路径上的每个状态。"""
        for depth in range(len(path) - 1, -1, -1):
            self._invoke("exit", path[: depth + 1])

    def _enter_initial(self):
        root = self.active_path[0]
        self._enter_node([root])
        self._enter_default_descendants([root])

    # ---------- 触发 ----------
    def trigger(self, event_name: str, context: Optional[Dict[str, Any]] = None):
        context = context or {}
        self._ctx = context
        # 从叶子向根冒泡查找能处理该事件的状态
        for depth in range(len(self.active_path) - 1, -1, -1):
            prefix = self.active_path[: depth + 1]
            node = self._node_config(prefix)
            target = node.get("transitions", {}).get(event_name)
            if target is None:
                continue

            # 支持完整写法 {"target":..., "guard":...}
            guard_name = None
            if isinstance(target, dict):
                guard_name = target.get("guard")
                target = target.get("target", target)
            if not isinstance(target, str):
                continue

            # guard 条件检查
            if guard_name:
                from .state_machine import GUARD_REGISTRY
                guard_fn = GUARD_REGISTRY.get(guard_name)
                if callable(guard_fn) and not guard_fn(context):
                    return None, f"Guard [{guard_name}] 不满足（位于 {self.current_leaf}）"

            # 内部转移：#state（原地执行，不离开状态）
            if target.startswith("#"):
                self._invoke("internal", prefix, extra={"event": event_name})
                return self.current_state_id, self._leaf_content()

            self._transition_to(prefix, target, event_name)
            return self.current_state_id, self._leaf_content()

        return None, f"无人处理事件 [{event_name}]（已冒泡至根）"

    def _transition_to(self, from_prefix: List[str], target: str, event: str):
        target_path = self._find_path(target)
        if not target_path:
            return
        self.active_path = list(target_path)  # 先设为目标路径（叶子态）
        # 公共祖先长度
        common = 0
        while (common < len(from_prefix) and common < len(target_path)
               and from_prefix[common] == target_path[common]):
            common += 1
        # 退出当前路径中超出公共祖先的部分（从深到浅）
        for depth in range(len(from_prefix) - 1, common - 1, -1):
            self._invoke("exit", from_prefix[: depth + 1])
        # 进入目标路径中超出公共祖先的部分
        for depth in range(common, len(target_path)):
            self._enter_node(target_path[: depth + 1])
        # 进入目标的默认子孙（会沿 initial 维护 active_path 到叶）
        self._enter_default_descendants(target_path)
        self._invoke("transition", self.active_path,
                     extra={"from": "/".join(from_prefix), "event": event})

    # ---------- 历史返回 ----------
    def go_history(self, state_id: str):
        """返回到某复合状态，并恢复到其历史子状态。"""
        target_path = self._find_path(state_id)
        if not target_path or len(target_path) != 1:
            return
        node = self._node_config(target_path)
        if "substates" not in node:
            return
        self.active_path = list(target_path)
        self._enter_node(target_path)
        cached = self._history_cache.get(state_id)
        if cached:
            self._enter_specific_descendants(target_path, cached)
        elif node.get("initial"):
            self._enter_default_descendants(target_path)

    # ---------- 信息查询 ----------
    def _leaf_content(self) -> str:
        node = self._node_config(self.active_path)
        return node.get("content", f"[{self.current_leaf}]")

    def get_state_info(self) -> Dict[str, Any]:
        node = self._node_config(self.active_path)
        return {
            "id": self.current_leaf,
            "path": self.current_state_id,
            "content": node.get("content", ""),
            "on_enter": node.get("on_enter", ""),
            "on_exit": node.get("on_exit", ""),
            "available_events": self.available_events,
            "is_composite": self._is_composite(self.active_path),
        }

    @property
    def available_events(self) -> List[str]:
        events: List[str] = []
        # 叶子 + 所有祖先的转移都可冒泡触发
        for depth in range(len(self.active_path)):
            prefix = self.active_path[: depth + 1]
            node = self._node_config(prefix)
            events.extend(node.get("transitions", {}).keys())
        # 去重保序
        seen, out = set(), []
        for e in events:
            if e not in seen:
                seen.add(e)
                out.append(e)
        return out

    def can_trigger(self, event_name: str) -> bool:
        return event_name in self.available_events

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.history[-limit:]

    # ---------- 内部 ----------
    def _invoke(self, action_type: str, path: List[str], extra: Optional[Dict[str, Any]] = None):
        state_id = path[-1]
        node = self._node_config(path)
        description = node.get(f"on_{action_type}", "")
        if action_type == "transition":
            description = node.get("on_enter", "")

        # 执行已注册动作（当描述为注册名时）
        from .state_machine import ACTION_REGISTRY
        action_fn = ACTION_REGISTRY.get(description)
        if callable(action_fn):
            try:
                action_fn(self._ctx or {},
                          {"state": state_id, "type": action_type, "extra": extra or {}})
            except Exception:
                pass

        if callable(self.on_action):
            detail = {"description": description, "path": "/".join(path)}
            if extra:
                detail.update(extra)
            self.on_action(action_type, state_id, detail)

        if action_type in ("enter", "exit", "internal", "transition"):
            self.history.append({
                "action": action_type,
                "state": "/".join(path),
                "event": (extra or {}).get("event", ""),
                "time": time.time(),
            })
