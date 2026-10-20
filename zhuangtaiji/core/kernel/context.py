# -*- coding: utf-8 -*-
"""
Context：服务容器 + 生命周期 + 依赖声明（对应 Cordis 的 Context / Fiber）
=====================================================================

现状对照：本项目当前**没有 ctx**。服务以模块级全局字典存在——
``GUARD_REGISTRY``、``ACTION_REGISTRY``（core/state_machine.py:11,25）、
``_ADAPTERS``、``_SECTION_OF``（core/engine_adapters.py:403,413）、
``PluginRegistry._plugins``（core/plugin.py:47）、``web/server.py`` 的 ``ORCH``。
结果是：无法在一个进程内跑两份互不干扰的配置，也无法整体卸载。

值得注意的是 ``core/state_machine.py:57-60`` **已经在手写 scope 的雏形**：

    self.guards = dict(GUARD_REGISTRY)      # 构造时快照全局表
    if isinstance(guards, dict):
        self.guards.update(guards)          # 实例级覆盖

但这只覆盖了 guards 一处，且是"构造时快照"——运行时新增的 guard 不会生效，
也无法撤销。本模块把这种需求泛化为通用的 ``ctx.provide`` + ``isolate``。

**生命周期状态机**（与 ``prototype/fiber_model.json`` 的模型一一对应，
并由 ``test_kernel.py`` 的锁步用例验证）：

    PENDING ──provide 且 inject 满足──▶ ACTIVE
    ACTIVE  ──provider 被撤回────────▶ PENDING
    ACTIVE  ──apply 抛错──────────────▶ FAILED
    FAILED  ──provide 且 inject 满足──▶ ACTIVE
    任意     ──dispose────────────────▶ DISPOSED

**与 Cordis 的刻意差异**（避免过度移植）：

* 不实现 Proxy + trap，改用 ``__getattr__``（Python 惯用法，可读性更好）；
* 不实现 6 态 fiber，合并 LOADING/UNLOADING 进三态；
* 不做 epoch 字符串指纹，改为显式 ``_recheck()`` 遍历
  （本项目规模下代价可接受；若要规模化，可接 ``difference_engine.ReactiveTracker``）；
* 全程同步：本项目没有异步运行时，``effect`` 不返回 awaitable。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from .disposable import Disposable, DisposableList
from .events import EventBus

ACTIVE = "ACTIVE"
PENDING = "PENDING"
DISPOSED = "DISPOSED"
FAILED = "FAILED"


class Plugin:
    """一个可挂载的插件：``apply(ctx, config)`` + 依赖声明 ``inject``。

    :param name: 插件名（用于日志与诊断）。
    :param apply: 主体函数，收 ``(ctx, config)``；返回的清理器会被自动托管。
    :param inject: 必需服务名序列；未全部满足时插件停在 PENDING。
    :param config: 该插件实例的配置（由 loader 从分层配置注入）。
    """

    def __init__(self, name: str, apply: Callable[[Any, Any], Any],
                 inject: Sequence[str] = (), config: Any = None):
        self.name = name
        self.apply = apply
        self.inject = tuple(inject)
        self.config = config


def _as_plugin(obj: Any) -> Plugin:
    """把函数 / 对象归一化为 Plugin（函数上可用属性声明 inject）。"""
    if isinstance(obj, Plugin):
        return obj
    if callable(obj):
        return Plugin(
            name=getattr(obj, "__name__", "anonymous"),
            apply=obj,
            inject=tuple(getattr(obj, "inject", ())),
            config=getattr(obj, "config", None),
        )
    raise TypeError(f"cannot mount {type(obj).__name__} as a plugin")


class _Mount:
    """一次挂载记录。``ctx`` 的状态即该挂载的当前生命周期状态。"""

    __slots__ = ("ctx", "plugin")

    def __init__(self, ctx: "Context", plugin: Plugin):
        self.ctx = ctx
        self.plugin = plugin


class Context:
    """服务容器与生命周期载体。自行创建根实例，其余通过 ``plugin``/``extend`` 派生。"""

    def __init__(self, parent: Optional["Context"] = None, name: str = "root",
                 isolated: Sequence[str] = ()):
        self._parent = parent
        self._name = name
        self._isolated = set(isolated)
        self._services: Dict[str, Any] = {}
        self._children: List["Context"] = []
        self._disposables = DisposableList()
        self._state = ACTIVE
        self._mount_errors: List[str] = []
        self._rechecking = False
        self.events = EventBus()
        if parent is not None:
            parent._children.append(self)
        else:
            self._mounts: List[_Mount] = []      # 只有根持有全局挂载表

    # ------------------------------------------------------------------
    # 基本信息
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> str:
        return self._state

    @property
    def root(self) -> "Context":
        node = self
        while node._parent is not None:
            node = node._parent
        return node

    @property
    def _all_mounts(self) -> List[_Mount]:
        return self.root.__dict__.setdefault("_mounts", [])

    def __repr__(self) -> str:
        return f"<Context {self._name} {self._state} services={sorted(self._services)}>"

    # ------------------------------------------------------------------
    # 服务容器
    # ------------------------------------------------------------------
    def provide(self, key: str, value: Any) -> Disposable:
        """注册服务，返回撤销句柄；重复注册直接报错（fail loud）。

        撤销时会**重算依赖**：依赖该服务的 ACTIVE 插件退回 PENDING 并回收
        自己的 effect（对应 Cordis 的 epoch 变化 → ``_unload``）。
        """
        self._assert_active()
        if key in self._services:
            raise KeyError(
                f'service "{key}" is already registered in context "{self._name}"'
            )
        self._services[key] = value
        self.events.emit("internal/service",
                         {"ctx": self, "key": key, "value": value})
        self.root._recheck()

        def _off() -> None:
            if self._services.pop(key, None) is not None:
                self.root._recheck()

        return Disposable(_off, label=f"provide:{key}")

    def get(self, key: str, default: Any = None) -> Any:
        """查找服务：本作用域 → 祖先；被 isolate 的名字不向上查找。"""
        node: Optional[Context] = self
        while node is not None:
            if key in node._services:
                return node._services[key]
            if key in node._isolated:
                return default          # 隔离名不穿透到祖先
            node = node._parent
        return default

    def require(self, key: str) -> Any:
        """查找服务，缺失即报错并给出可操作的提示。"""
        sentinel = object()
        value = self.get(key, sentinel)
        if value is sentinel:
            raise LookupError(
                f'required service "{key}" is not available in context "{self._name}"; '
                f"declare it in `inject` or provide it before use"
            )
        return value

    def has(self, key: str) -> bool:
        return self.get(key, None) is not None

    def services(self) -> Dict[str, Any]:
        """本作用域可见的服务快照（供自省 / 诊断）。"""
        chain: List[Context] = []
        node: Optional[Context] = self
        while node is not None:
            chain.append(node)
            node = node._parent
        out: Dict[str, Any] = {}
        for scope in reversed(chain):          # 祖先 → 后代：后代覆盖祖先
            out.update(scope._services)
            for name in scope._isolated:       # 隔离名在当前层截断继承
                out.pop(name, None)
        return out

    def __getattr__(self, item: str) -> Any:
        """``ctx.engines`` 直接解析服务（下划线名不拦截）。"""
        if item.startswith("_"):
            raise AttributeError(item)
        services = object.__getattribute__(self, "_services")
        if item in services:
            return services[item]
        raise AttributeError(
            f'context "{object.__getattribute__(self, "_name")}" has no service '
            f'"{item}"; available: {sorted(services)}'
        )

    # ------------------------------------------------------------------
    # effect：注册即可逆
    # ------------------------------------------------------------------
    def effect(self, fn: Callable[[], Any], label: str = "") -> Disposable:
        """执行 ``fn`` 并把它的返回值登记为可逆清理。

        ``fn`` **立即执行**（注册即生效）；返回值可为 ``None`` / 可调用对象 /
        ``Disposable`` / 它们的列表。返回的句柄被 ``dispose()`` 时先执行清理、
        再从 owner 的清单里摘除；owner 卸载时由 ``DisposableList`` 逆序回收。
        """
        self._assert_active()
        result = fn()
        inner = Disposable.of(result, label)
        holder = self._disposables.add(inner)

        def _dispose() -> None:
            inner.dispose()
            self._disposables.remove(holder)

        return Disposable(_dispose, label or "effect")

    # ------------------------------------------------------------------
    # 事件（注册自动挂到本 context 的 effect 上）
    # ------------------------------------------------------------------
    def on(self, name: str, cb: Callable, mode: str = "emit",
           prepend: bool = False) -> Disposable:
        """注册监听器；context 卸载时自动退订。"""
        self._assert_active()
        handle = self.events.on(name, cb, mode=mode, prepend=prepend)
        holder = self._disposables.add(handle)

        def _dispose() -> None:
            handle.dispose()
            self._disposables.remove(holder)

        return Disposable(_dispose, label=f"on:{name}")

    def emit(self, name: str, payload: Any = None) -> None:
        self.events.emit(name, payload)

    def waterfall(self, name: str, payload: Any,
                  inner: Optional[Callable[[Any], Any]] = None) -> Any:
        return self.events.waterfall(name, payload, inner=inner)

    def serial(self, name: str, payload: Any = None) -> Any:
        return self.events.serial(name, payload)

    # ------------------------------------------------------------------
    # 作用域
    # ------------------------------------------------------------------
    def extend(self, name: str = "", isolated: Sequence[str] = ()) -> "Context":
        """派生子作用域：服务查找向父级回退，生命周期挂在父级上。"""
        child = Context(parent=self, name=name or f"{self._name}/child",
                        isolated=isolated)
        self._disposables.add(Disposable(child.dispose, label=f"scope:{child._name}"))
        return child

    def isolate(self, *names: str) -> "Context":
        """隔离作用域：``names`` 里的服务只在本子树内解析，不穿透到祖先。

        这是「同一进程内两份互不干扰的配置」的实现方式——每个 Orchestrator
        挂在自己的 isolate 作用域里，同名引擎互不可见。
        """
        return self.extend(name=f"{self._name}/isolate", isolated=names)

    # ------------------------------------------------------------------
    # 插件挂载与生命周期转移
    # ------------------------------------------------------------------
    def plugin(self, obj: Any, config: Any = None) -> "Context":
        """挂载插件，返回该插件自己的 context。

        ``inject`` 未满足时插件停在 ``PENDING``；对应 provider 上线后由
        ``provide()`` 触发的 ``_recheck()`` 自动激活。**加载顺序因此由依赖
        决定，不由代码顺序决定。**
        """
        self._assert_active()
        plugin = _as_plugin(obj)
        if config is not None:
            plugin = Plugin(plugin.name, plugin.apply, plugin.inject, config)

        child = Context(parent=self, name=plugin.name)
        # 插件的生命周期是父级上的一个 effect —— 父级卸载即级联卸载
        self._disposables.add(Disposable(child.dispose, label=f"plugin:{plugin.name}"))

        mount = _Mount(child, plugin)
        self._all_mounts.append(mount)
        child._state = PENDING
        self.root._recheck()
        return child

    def _activate(self, mount: _Mount) -> None:
        """PENDING → ACTIVE（成功）或 → FAILED（apply 抛错）。

        注意状态在 apply **成功之后**才置为 ACTIVE：这样"PENDING --provide-->
        ACTIVE | FAILED"与 ``fiber_model.json`` 的模型严格 1:1，不存在外部
        观测不到的瞬时中间态。重入由 ``_recheck`` 的 ``_rechecking`` 闸门挡住。
        """
        child, plugin = mount.ctx, mount.plugin
        try:
            result = plugin.apply(child, plugin.config)
        except Exception as exc:
            child._state = FAILED
            child._mount_errors.append(f"{plugin.name}: {exc!r}")
            child._disposables.rollback()          # 失败必须回滚已注册 effect
            self.events.emit("internal/plugin-failed",
                             {"context": child, "plugin": plugin, "error": exc})
            print(f"[kernel] plugin failed: {plugin.name}: {exc!r}")
            return
        child._disposables.add(Disposable.of(result, label=f"apply:{plugin.name}"))
        child._state = ACTIVE
        self.events.emit("internal/plugin-active", {"context": child, "plugin": plugin})

    def _deactivate(self, mount: _Mount) -> None:
        """ACTIVE/FAILED → PENDING：回收插件自身的 effect，但保留挂载记录。

        对应 Cordis 的 epoch 变化 → ``_unload``，随后若依赖恢复则可 ``_reload``。
        """
        child, plugin = mount.ctx, mount.plugin
        child._disposables.dispose()               # 逆序回收（不置 DISPOSED）
        child._services.clear()
        child.events.clear()
        child._mount_errors.clear()
        child._state = PENDING
        self.events.emit("internal/plugin-released", {"context": child, "plugin": plugin})

    def _recheck(self) -> None:
        """按依赖重算全部挂载状态（对应 Cordis 的 ``notify`` → ``refresh``）。

        处理两个方向：

        * PENDING 且 inject 已满足 → 激活；
        * ACTIVE/FAILED 但 inject 已不满足 → 退回 PENDING。

        循环至稳定，以覆盖"激活过程中又 provide 了新服务"的链式情形。
        可重入（``_rechecking`` 闸门），避免 provide 与 recheck 相互递归。
        """
        if self._rechecking:
            return
        self._rechecking = True
        try:
            changed = True
            while changed:
                changed = False
                for mount in list(self._all_mounts):
                    child, plugin = mount.ctx, mount.plugin
                    if child._state in (DISPOSED,):
                        continue
                    satisfied = all(child.has(k) for k in plugin.inject)
                    if child._state == PENDING and satisfied:
                        self._activate(mount)
                        changed = True
                    elif child._state in (ACTIVE, FAILED) and not satisfied:
                        self._deactivate(mount)
                        changed = True
        finally:
            self._rechecking = False

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------
    def pending_plugins(self) -> List[str]:
        """仍停在 PENDING 的插件名。

        这正是排查「插件配置写了但静默不生效」的确定入口——当前项目没有等价物，
        只能靠人去读代码推断为什么某个 `_section_provider` 返回了空字典。
        """
        return [m.plugin.name for m in self._all_mounts if m.ctx._state == PENDING]

    def active_plugins(self) -> List[str]:
        return [m.plugin.name for m in self._all_mounts if m.ctx._state == ACTIVE]

    def mount_states(self) -> Dict[str, str]:
        """``{插件名: 状态}`` 快照（供 UI 渲染 / 锁步测试比对）。"""
        return {m.plugin.name: m.ctx._state for m in self._all_mounts}

    def inspect(self) -> Dict[str, Any]:
        """自省快照：把内核当前可观测面汇成一份结构化数据。

        用途：调试、UI 诊断面板、锁步测试比对。覆盖四类信息：

        * **services**：本作用域可见的全部服务名（含祖先、隔离截断后的结果）；
        * **engines**：名为 ``engines`` 的服务中的引擎实例键（若有）；
        * **bindings**：名为 ``bindings`` 的服务中的编排绑定数量（若有）；
        * **pending / active**：插件生命周期状态。

        返回**副本**，调用方改它不影响内核；读它也不触发 ``_recheck``。
        """
        engines = self.get("engines")
        bindings = self.get("bindings")
        snapshot: Dict[str, Any] = {
            "name": self._name,
            "state": self._state,
            "services": sorted(self.services().keys()),
            "pending_plugins": self.pending_plugins(),
            "active_plugins": self.active_plugins(),
            "mount_states": self.mount_states(),
        }
        if isinstance(engines, dict):
            snapshot["engines"] = sorted(engines.keys())
        elif engines is not None:
            snapshot["engines"] = f"<{type(engines).__name__}>"
        if bindings is not None:
            snapshot["bindings"] = (len(bindings)
                                    if isinstance(bindings, (list, tuple, dict))
                                    else f"<{type(bindings).__name__}>")
        return snapshot

    # ------------------------------------------------------------------
    # 卸载
    # ------------------------------------------------------------------
    def _assert_active(self) -> None:
        if self._state == DISPOSED:
            raise RuntimeError(f'context "{self._name}" is disposed; cannot register')

    def dispose(self) -> None:
        """卸载：逆序回收全部 effect（含子插件与子作用域），清空服务。"""
        if self._state == DISPOSED:
            return
        self._state = DISPOSED
        self._disposables.dispose()
        self.events.clear()
        self._services.clear()
        # 把自身与全部后代从根的挂载表里摘除
        mounts = self.root.__dict__.get("_mounts")
        if mounts is not None:
            for mount in list(mounts):
                if mount.ctx is self or _is_descendant(mount.ctx, self):
                    mounts.remove(mount)
        if self._parent is not None:
            try:
                self._parent._children.remove(self)
            except ValueError:
                pass

    def effect_count(self) -> int:
        """当前存活的可逆注册数（不变式断言用）。"""
        return len(self._disposables)


def _is_descendant(node: Context, ancestor: Context) -> bool:
    """``node`` 是否位于 ``ancestor`` 的子树内。"""
    cur: Optional[Context] = node._parent
    while cur is not None:
        if cur is ancestor:
            return True
        cur = cur._parent
    return False
