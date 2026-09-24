# -*- coding: utf-8 -*-
"""插件注册表与发现（P0-1 扩展接缝）。

* ``EnginePlugin`` —— 描述一个可插拔范式：kind / label / 构建器 / specs 提供者。
* ``PluginRegistry`` —— **``core.registries.engines`` 的兼容门面**。

历史上 ``PluginRegistry`` 自己持有一张 class 级字典（``_plugins``），而同一份
「kind → config 段名」的信息在 ``core/engine_adapters.py`` 里又存了一份，另有
若干份散落在 ``web/server.py``（三处）与 ``ui/*_tab.py``（两处）。新增一个范式
需要在多处补写，漏一处就出现"某个入口看不到新范式"。

自 P1-2 起信息只有**一处**：``core.registries.engines``。本模块保留历史 API
（``register`` / ``get`` / ``all`` / ``kinds`` / ``discover``），内部全部转发到
那张表——**因此"一张表"与"一个视图"不可能漂移**。
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from . import engine_adapters as adapters
from .engine_base import BaseAdapter, EngineResult
from .registries import engine_kinds, engine_of, register_engine


def _section_provider(section: str) -> Callable[[], Dict[str, Dict]]:
    """构造一个"按需读取某个 config 段"的提供者。

    注意它**不再吞异常**：过去写的是 ``except Exception: return {}``——
    配置读坏了会表现为"这个范式没有实例"，用户完全无从判断。
    现在只把"段不存在"视为空，其余错误原样抛出。
    """
    def _provider() -> Dict[str, Dict]:
        from .config import load_config
        bucket = load_config().get(section)
        return bucket if isinstance(bucket, dict) else {}
    return _provider


# ==========================================================
# 插件定义
# ==========================================================
@dataclass
class EnginePlugin:
    """一个可插拔的决策范式。

    :param kind: 唯一标识，如 ``"decision_table"``。
    :param label: 展示名。
    :param description: 一句话说明。
    :param engine_cls: 适配器类，签名 ``(name=..., on_event=...) -> BaseAdapter``。
    :param specs_provider: ``() -> {实例名: spec}``；默认按 ``section`` 从配置读取。
    :param section: 该范式在 ``config.json`` 中的顶层段名；``specs_provider``
        未显式给出时用它派生。**这是取代过去多处重复映射的关键字段。**
    """

    kind: str
    label: str
    description: str = ""
    engine_cls: Type[BaseAdapter] = None
    specs_provider: Callable[[], Dict[str, Dict]] = None
    section: str = ""

    def __post_init__(self) -> None:
        if not self.section:
            # 从引擎注册表反查（builtin 范式已在 engine_adapters 登记过 section）
            meta = engine_of(self.kind)
            if meta is not None:
                self.section = meta.section
        if self.specs_provider is None:
            if not self.section:
                raise ValueError(
                    f"EnginePlugin({self.kind!r}) 需要 section 或 specs_provider 之一")
            self.specs_provider = _section_provider(self.section)

    def specs(self) -> Dict[str, Dict]:
        """该范式在配置中的全部实例（``{实例名: spec}``）。"""
        return self.specs_provider() if callable(self.specs_provider) else {}

    def build(self, name: str, on_event=None) -> BaseAdapter:
        """按实例名构造引擎。

        走 ``build_adapter`` 这**唯一一条**构造路径，因此错误信息与配置驱动的
        构造完全一致（未知 kind / 段缺失 / 实例不存在都给出可操作提示）。
        """
        from .config import load_config
        return adapters.build_adapter(self.kind, name, load_config(),
                                      on_event=on_event)


# ==========================================================
# 注册表（engines 的兼容门面）
# ==========================================================
class PluginRegistry:
    """引擎插件的兼容门面；数据真身是 ``core.registries.engines``。"""

    @classmethod
    def register(cls, plugin: EnginePlugin):
        """登记一个插件范式。

        :returns: ``Disposable``；撤销后该范式从所有入口（Web/UI/编排）一并消失。
        :raises KeyError: kind 已注册（不再静默覆盖）。
        """
        if not plugin.section:
            plugin.section = plugin.kind
        return register_engine(plugin.kind, plugin.engine_cls, plugin.section,
                               plugin.label, plugin.description)

    @classmethod
    def get(cls, kind: str) -> Optional[EnginePlugin]:
        """按 kind 取插件（不存在返回 ``None``）。"""
        meta = engine_of(kind)
        return _to_plugin(meta) if meta is not None else None

    @classmethod
    def all(cls) -> List[EnginePlugin]:
        """全部已注册插件，按 kind 排序。"""
        return [_to_plugin(m) for m in engine_kinds()]

    @classmethod
    def kinds(cls) -> List[str]:
        """全部已注册 kind（``_validate_spec`` 用它判"范式是否存在"）。"""
        return [m.kind for m in engine_kinds()]

    @classmethod
    def discover(cls, package_name: str = "core.plugins") -> List[str]:
        """扫描插件包，导入所有模块并收集 ``PLUGIN`` 对象。

        :param package_name: 要扫描的包名。
        :returns: 本次新发现的 kind 列表。
        :raises ImportError: 某个插件模块导入失败——**过去这里 ``except: continue``
            静默跳过**，导致"我写的插件没出现"且毫无提示。现在带上文件名抛错。
        """
        try:
            pkg = importlib.import_module(package_name)
        except ModuleNotFoundError:
            return []
        newly: List[str] = []
        for mod in pkgutil.iter_modules(pkg.__path__, package_name + "."):
            try:
                m = importlib.import_module(mod.name)
            except Exception as exc:
                raise ImportError(
                    f"插件模块 {mod.name} 导入失败：{exc!r}。"
                    f"（它位于 {package_name}/，修好或移走该文件即可）"
                ) from exc
            plugin = getattr(m, "PLUGIN", None)
            if isinstance(plugin, EnginePlugin) and plugin.kind not in cls.kinds():
                cls.register(plugin)
                newly.append(plugin.kind)
        return newly


def _to_plugin(meta) -> EnginePlugin:
    """把注册表条目转成 ``EnginePlugin`` 视图（保持历史 API 可用）。"""
    return EnginePlugin(
        kind=meta.kind,
        label=meta.label,
        description=meta.description,
        engine_cls=meta.adapter_cls,
        specs_provider=_section_provider(meta.section),
        section=meta.section,
    )


def ensure_discovered() -> List[str]:
    """确保已扫描插件目录（幂等）。

    :returns: 首次调用时新发现的 kind 列表；已扫描过则返回空列表。
    """
    return PluginRegistry.discover("core.plugins")
