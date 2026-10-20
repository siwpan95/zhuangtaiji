# -*- coding: utf-8 -*-
"""
分层装配：patch 算法 + 组 / 隔离作用域（对应 Cordis 的 Loader + Include）
=====================================================================

现状对照：本项目 ``core/config.py`` 只有一个 ``load_config()`` 直接读
``config.json``；同一份「kind → config 段名」映射在**两处重复**
（``core/engine_adapters.py:413`` 的 ``_SECTION_OF`` 与
``web/server.py:326-334`` 的 ``kinds`` 字典）——一旦新增范式必然漏改一处。

本模块给出修正版：**配置是分层的 patch 列表，装配是唯一的纯函数。**

三条被移植过来的关键语义（均来自 DeepSeek Harness 的实证结论）：

1. **空根 + 分层 patch**：根 entry 列表初始为空，产品差异全部表达为 patch。
   本项目对应场景——内置 demo 编排在 base 层，用户自定义在 overlay 层。
2. **按 id 整键替换，不做深合并**：``{"id": "fsm1", "config": {...}}`` 会
   整体替换该行的 ``config``，而不是逐字段合并。好处是"某字段最终是谁给的
   只有一个答案"；代价是 override 必须重述要保留的字段。
3. **insert 之后立即重建索引**：否则同一层里"后一条 patch 无法配置前一条
   insert 出来的行"——这是 Harness 对上游 Cordis 的著名修复。

**只移植 config-only 热更新**：本项目不需要模块热重载，改配置重跑
``compose + mount`` 即可（见 ``hot_reload``），避免引入依赖图分析。
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Sequence

from .context import Context, Plugin

Layer = List[Dict[str, Any]]
Patch = Dict[str, Any]

# entry 上允许携带的元数据字段（其余字段会被 patch 视作 config 级覆盖）
ENTRY_META = ("id", "name", "group", "isolate", "disabled")


def _warn_default(message: str) -> None:
    print(f"[loader] {message}")


def build_index(entries: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """递归索引所有 ``id`` → entry（只下钻到 ``group`` 的子列表）。"""
    index: Dict[str, Dict[str, Any]] = {}

    def walk(items: Sequence[Dict[str, Any]]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            eid = item.get("id")
            if eid:
                index[eid] = item
            if item.get("group") and isinstance(item.get("config"), list):
                walk(item["config"])

    walk(entries)
    return index


def apply_patches(entries: Sequence[Dict[str, Any]], patches: Sequence[Patch],
                  warn: Callable[[str], None] = _warn_default) -> Layer:
    """按 id 应用 patch 列表，返回新的 entry 列表。

    :param entries: 基底 entry 列表（根配置，通常为 ``[]``）。
    :param patches: patch 列表。``insert`` 追加新行；其余字段按 id 整键覆盖。
    :param warn: 诊断输出（目标缺失等非致命问题只警告，不抛错）。

    **不修改入参**：有 patch 时深拷贝，无 patch 时浅拷贝（保留 entry 引用）。
    这是"配置可重复热重载"的前提——否则 patch 结果会被烘焙进缓存。
    """
    if not patches:
        return list(entries)

    data: List[Dict[str, Any]] = copy.deepcopy(list(entries))
    index = build_index(data)

    for patch in patches:
        if not isinstance(patch, dict):
            warn(f"patch is not a mapping, skipped: {patch!r}")
            continue

        overrides = {k: v for k, v in patch.items() if k != "insert"}

        # ---- insert：往 group 的子列表（或顶层）追加新行 ----
        if "insert" in patch:
            inserted = patch["insert"] or []
            target_id = patch.get("id")
            if target_id is None:
                data.extend(copy.deepcopy(list(inserted)))
            else:
                target = index.get(target_id)
                if target is None:
                    warn(f"patch insert: entry {target_id!r} not found")
                    continue
                if not target.get("group") or not isinstance(
                        target.get("config"), list):
                    warn(f"patch insert: entry {target_id!r} is not a group")
                    continue
                target["config"].extend(copy.deepcopy(list(inserted)))
            # 关键：插入后立即使其可被同层后续 patch 命中
            index = build_index(data)
            continue

        # ---- 覆盖：必须有 id ----
        target_id = overrides.pop("id", None)
        if not target_id:
            warn("patch without `id` and without `insert` is ignored")
            continue
        target = index.get(target_id)
        if target is None:
            warn(f"patch target {target_id!r} not found")
            continue

        declared = overrides.pop("name", None)
        if declared is not None and declared != target.get("name"):
            warn(f"patch target {target_id!r} name mismatch "
                 f"(expected {target.get('name')!r}, patch says {declared!r}); skipped")
            continue

        for key, value in overrides.items():
            target[key] = value        # 整键替换，不深合并

    return data


def compose(*layers: Sequence[Patch]) -> Layer:
    """把多层 patch 摊平成一个 patch 列表。

    顺序即优先级（后写覆盖先写），对应 Harness 的
    ``bundle 层 → profile 层 → home 层 → --patch overlay``。
    """
    flat: Layer = []
    for layer in layers:
        flat.extend(layer or [])
    return flat


class Loader:
    """把 entry 列表挂载成插件树。

    :param ctx: 宿主 context。
    :param factories: ``name -> 插件工厂``。工厂签名 ``(config) -> Plugin``
        或直接给 ``Plugin`` / 可调用对象。
    :param required: 必败清单——这些 id 若未激活则 ``mount`` 抛错（fail loud）。
    """

    def __init__(self, ctx: Context, factories: Dict[str, Any],
                 required: Sequence[str] = ()):
        self.ctx = ctx
        self.factories = dict(factories)
        self.required = tuple(required)
        self.mounted: Dict[str, Context] = {}
        self.warnings: List[str] = []

    # ------------------------------------------------------------------
    def warn(self, message: str) -> None:
        self.warnings.append(message)
        _warn_default(message)

    def mount(self, entries: Sequence[Dict[str, Any]],
              root: Optional[Context] = None) -> int:
        """挂载 entry 列表，返回成功挂载的条目数。

        ``group`` 行进入隔离作用域（其 ``isolate`` 列出的服务不会外泄）；
        ``disabled`` 行跳过但会记录，便于诊断"配置写了却没生效"。
        """
        host = root or self.ctx
        count = 0
        for entry in entries:
            if not isinstance(entry, dict):
                self.warn(f"entry is not a mapping, skipped: {entry!r}")
                continue
            if entry.get("disabled"):
                self.warn(f"entry {entry.get('id')!r} is disabled; not mounted")
                continue

            if entry.get("group"):
                child = self._mount_group(host, entry)
                if child is not None:
                    count += 1
                continue

            if self._mount_leaf(host, entry) is not None:
                count += 1

        if self.required:
            self.audit()
        return count

    def _mount_group(self, host: Context, entry: Dict[str, Any]) -> Optional[Context]:
        isolate_names = entry.get("isolate") or {}
        isolated = tuple(k for k, v in isolate_names.items() if v)
        scope = host.isolate(*isolated)
        scope._name = entry.get("id") or "group"       # 便于诊断定位
        subs = entry.get("config") or []
        for sub in subs:
            if not isinstance(sub, dict):
                self.warn(f"group {entry.get('id')!r}: sub-entry is not a mapping")
                continue
            if sub.get("disabled"):
                self.warn(f"group {entry.get('id')!r}: sub-entry "
                          f"{sub.get('id')!r} is disabled; not mounted")
                continue
            self._mount_leaf(scope, sub)
        if entry.get("id"):
            self.mounted[entry["id"]] = scope
        return scope

    def _mount_leaf(self, host: Context, entry: Dict[str, Any]) -> Optional[Context]:
        name = entry.get("name")
        if not name:
            self.warn(f"entry {entry.get('id')!r} has no `name`; not mounted")
            return None

        factory = self.factories.get(name)
        if factory is None:
            self.warn(f"entry {entry.get('id')!r}: unknown plugin {name!r}")
            return None

        plugin = self._materialize(factory, entry)
        child = host.plugin(plugin)
        if entry.get("id"):
            self.mounted[entry["id"]] = child
        return child

    @staticmethod
    def _materialize(factory: Any, entry: Dict[str, Any]) -> Plugin:
        """把工厂 + entry 合成 Plugin 对象。"""
        config = entry.get("config")
        if isinstance(factory, Plugin):
            return Plugin(factory.name, factory.apply, factory.inject, config)
        if callable(factory):
            built = factory(config)
            plugin = built if isinstance(built, Plugin) else Plugin(
                name=getattr(factory, "__name__", "plugin"),
                apply=built, config=config)
            return plugin
        raise TypeError(f"factory for {entry.get('name')!r} is not callable")

    # ------------------------------------------------------------------
    def audit(self) -> None:
        """必败清单审计：必需条目未挂载即抛错（区分于"可选行只警告"）。"""
        missing = [eid for eid in self.required if eid not in self.mounted]
        if missing:
            raise RuntimeError(
                f"startup failed: required entries not mounted: {missing}")

    def status(self) -> Dict[str, str]:
        """各已挂载条目的状态（供自省 / UI 渲染，不必硬编码）。"""
        return {eid: ctx.state for eid, ctx in self.mounted.items()}


def hot_reload(ctx: Context, base: Layer, patches: Sequence[Patch],
               factories: Dict[str, Any], required: Sequence[str] = ()
               ) -> Loader:
    """config-only 热更新：卸载旧树、重算 patch、重新挂载。

    对应 Harness「改 YAML 走 ``Include.refresh()``，不动模块系统」的路径。
    注意其**已知边界**：被重新挂载的插件会拿到全新实例，因此
    "运行中状态"不会保留——需要保留的状态必须由宿主服务持有（见 demo 的
    ``ctx.orchestrations``），而不能藏在插件实例里。
    """
    ctx.dispose()
    fresh = Context(name="root")
    entries = apply_patches(base, patches, warn=lambda m: print(f"[loader] {m}"))
    loader = Loader(fresh, factories, required)
    loader.mount(entries)
    return loader
