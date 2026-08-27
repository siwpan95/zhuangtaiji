# -*- coding: utf-8 -*-
"""
插件注册表与发现（P0-1 扩展接缝）
================================

* ``EnginePlugin`` —— 描述一个可插拔范式：kind / label / 构建器 / specs 提供者。
* ``PluginRegistry`` —— 注册与查询；启动时自动扫描 ``core.plugins`` 包，发现
  第三方范式（证明「加一个文件即可扩展，不动核心代码」）。

内置 7 个范式在导入本模块时自动注册；``core/plugins/`` 下任意 ``*.py`` 只要
暴露一个 ``PLUGIN = EnginePlugin(...)`` 对象即被自动加载。
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from . import engine_adapters as adapters
from .engine_base import BaseAdapter, EngineResult


# ==========================================================
# 插件定义
# ==========================================================
@dataclass
class EnginePlugin:
    """一个可插拔的决策范式。"""
    kind: str                                  # 唯一标识，如 "decision_table"
    label: str                                 # 展示名
    description: str = ""
    engine_cls: Type[BaseAdapter] = None       # 构建器 (name, on_event) -> Engine
    specs_provider: Callable[[], Dict[str, Dict]] = lambda: {}  # name -> spec

    def build(self, name: str, on_event=None) -> BaseAdapter:
        eng = self.engine_cls(name=name, on_event=on_event)
        specs = self.specs_provider()
        eng.load(specs[name])
        return eng


# ==========================================================
# 注册表
# ==========================================================
class PluginRegistry:
    _plugins: Dict[str, EnginePlugin] = {}

    @classmethod
    def register(cls, plugin: EnginePlugin) -> None:
        cls._plugins[plugin.kind] = plugin

    @classmethod
    def get(cls, kind: str) -> Optional[EnginePlugin]:
        return cls._plugins.get(kind)

    @classmethod
    def all(cls) -> List[EnginePlugin]:
        return list(cls._plugins.values())

    @classmethod
    def kinds(cls) -> List[str]:
        return list(cls._plugins.keys())

    @classmethod
    def discover(cls, package_name: str = "core.plugins") -> List[str]:
        """扫描插件包，导入所有模块并收集 ``PLUGIN`` 对象。返回新发现的 kind 列表。"""
        try:
            pkg = importlib.import_module(package_name)
        except ModuleNotFoundError:
            return []
        newly = []
        for mod in pkgutil.iter_modules(pkg.__path__, package_name + "."):
            try:
                m = importlib.import_module(mod.name)
            except Exception:
                continue
            plugin = getattr(m, "PLUGIN", None)
            if isinstance(plugin, EnginePlugin) and plugin.kind not in cls._plugins:
                cls.register(plugin)
                newly.append(plugin.kind)
        return newly


# ==========================================================
# 注册内置 7 个范式（适配器）
# ==========================================================
def _section_provider(section: str) -> Callable[[], Dict[str, Dict]]:
    from .config import load_config
    def _provider():
        try:
            return load_config().get(section, {})
        except Exception:
            return {}
    return _provider


# 注：内置范式 specs 由 load_config 提供；这里仅登记构建器。
PluginRegistry.register(EnginePlugin(
    kind="state_machine", label="状态机 / HSM",
    description="状态 + 事件转移；层次/历史/守卫",
    engine_cls=adapters.StateMachineEngine,
    specs_provider=_section_provider("state_machines")))
PluginRegistry.register(EnginePlugin(
    kind="behavior_tree", label="行为树",
    description="根节点驱动 · 黑板共享 · 响应式",
    engine_cls=adapters.BehaviorTreeEngine,
    specs_provider=_section_provider("behavior_trees")))
PluginRegistry.register(EnginePlugin(
    kind="decision_tree", label="决策树",
    description="基于特征空间的一次性路由决策",
    engine_cls=adapters.DecisionTreeEngine,
    specs_provider=_section_provider("decision_trees")))
PluginRegistry.register(EnginePlugin(
    kind="petri_net", label="Petri 网",
    description="库所令牌 · 变迁使能 · 抑制弧",
    engine_cls=adapters.PetriEngine,
    specs_provider=_section_provider("petri_nets")))
PluginRegistry.register(EnginePlugin(
    kind="markov_chain", label="马尔可夫链",
    description="概率状态机 · 转移矩阵 · 稳态",
    engine_cls=adapters.MarkovEngine,
    specs_provider=_section_provider("markov_chains")))
PluginRegistry.register(EnginePlugin(
    kind="rule_engine", label="规则引擎 (RETE)",
    description="正向推理 · α/β 匹配 · 议程",
    engine_cls=adapters.RuleEngineAdapter,
    specs_provider=_section_provider("rule_engines")))
PluginRegistry.register(EnginePlugin(
    kind="difference_engine", label="差分引擎",
    description="有限差分递推 + 响应式差量",
    engine_cls=adapters.DifferenceEngineAdapter,
    specs_provider=_section_provider("difference_engine")))


def ensure_discovered() -> List[str]:
    """确保已扫描插件目录（幂等）。"""
    return PluginRegistry.discover("core.plugins")
