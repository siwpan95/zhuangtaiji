# zhuangtaiji × Cordis 内核重构方案

**副标题：论"状态机项目"与 Cordis 内核的同构性，以及哪些东西该拿、哪些该放**

| 项 | 值 |
|---|---|
| 目标仓库 | `zhuangtaiji`（Gitee: `siwpan/zhuangtaiji`，commit `fccb8e6`） |
| 项目规模 | 撰写时快照：6,660 行 Python，44 个文件，纯标准库（`requirements.txt` 仅 `openai`）（改造后实测见下方注） |
| 参照研究 | 《DeepSeek Harness 源码深度研究报告》（Cordis 参考实现 `deepseek-harness`，DSH） |
| 本方案附带 | 内核已落位 `core/kernel/`（48 项断言全通过，含自举一致性验证） |
| 落地进度 | P0–P4 全部完成并通过统一门禁（撰写机：通过 5 · 失败 0 · 环境跳过 1；内核 80 项断言）（口径见下方注） |
| 日期 | 2026-09-24 |

> **注（数值口径）**：上表「项目规模」「落地进度」是方案撰写时的**撰写机实测快照**，不是跨机恒定值。
> 改造后本机实测（提交 `66d94be`）：45 个 `.py`、10,992 行（含空行）；统一门禁
> `python tools/run_tests.py` 得到「通过 6 · 失败 0 · 环境跳过 0」——跳过数取决于该机是否装了带
> `tkinter` 的解释器（门禁会自动探测备用解释器并重试）。环境不同，行数与门禁分项都会随之变化。

---

## 摘要

你的判断是对的，而且比"适合"更强：**这是同构，不是类比。**

Cordis 的 `Fiber` 本身就是一台状态机，而 zhuangtaiji 的立身之本正是状态机引擎。更关键的是，本项目的 `core/difference_engine.py` 的"响应式脏检查"与 Cordis 的 "epoch 依赖指纹" **是同一种技术的两个名字**——用"指纹是否变化"代替"遍历重算"。

于是重构的性质变了：不是"给一个 Python 项目套上一个 TypeScript 框架"，而是**把一个已经具备 Cordis 四分之三要素的系统，补上缺失的那一块（Context），并把所有接线从"单向"改成"可逆"**。

本方案的结论可以压缩成一句话：

> **拿 Cordis 的四条纪律（effect 可逆、Context 容器、inject 声明依赖、派发模式契约）+ 两条工程纪律（空根分层 patch、fail-loud 分层）；放弃它的六项实现细节（Proxy、6 态 fiber、模块级 HMR、Typert/RPC、vendored 框架层、双 SDK 同步）。**

并且——这是本项目独有的红利——**内核自身的生命周期可以用项目自己的状态机引擎来验证**：`core/kernel/fiber_model.json` 用项目的配置格式描述 Fiber 生命周期，`test/test_kernel.py` 驱动真实内核与该模型**锁步前进**，逐步比对，任何不一致即测试失败。

### 落地进度总览

| 阶段 | 内容 | 状态 | 证据 |
|---|---|---|---|
| **P0-1** | 内核落位 `core/kernel/` | ✅ 完成 | 6 个文件；`core/__init__.py` 已登记 |
| **P0-2** | 统一门禁 `tools/run_tests.py` | ✅ 完成 | 区分 PASS / FAIL / ENV-SKIP；README 路径已修正 |
| **P0-3** | 内核断言迁入 `test/test_kernel.py` | ✅ 完成 | 48 项全通过 |
| — | 顺带修复：`test_verify.py` 从**无法运行**→**通过** | ✅ 完成 | `engine/progress_bar.py` 改延迟导入 tkinter |
| — | 消除重复来源：删除 `prototype/` | ✅ 完成 | 内容已全部迁入规范位置 |
| **P1-1** | 收编 GUARD/ACTION 注册表 | ✅ 完成 | 注册表移至 `core/registries.py`；9 项断言 |
| **P1-2** | 收编 `_ADAPTERS`/`_SECTION_OF` → `ctx.engines` | ✅ 完成 | 9 个范式一张表；7 项断言（含源码级反回归门禁） |
| **P1-3** | 收编 `PluginRegistry` + 修 `reset()` 泄漏监听器 | ✅ 完成 | 归并为注册表视图；真实 bug 已修；9 项断言 |
| **P2** | 事件三派发模式 + 引擎扩展点 | ✅ 核心完成 | `EventBus` 接内核；`engine/step` waterfall 可拦截 |
| **P3** | 配置分层 `patches` 段 | ✅ 完成 | `core/config.py` 的 `apply_config_patches`；6 项断言（`test_config_patches.py`） |
| **P4** | fail-loud 分层 + 配置校验 + 自省 | ✅ 完成 | 7 处静默降级已修（`core/plugin.py`/HSM/`config`）；load 期校验带路径；`ctx.inspect` 自省接口；4+3 项断言 |

**基线（改造前）**：`test_enhancements.py` 通过；`test_verify.py` **无法运行**（GUI 依赖污染）；`test_web_e2e.py` 需前端产物；无统一门禁。
**当前**：`python tools/run_tests.py` → **通过 3 / 失败 0 / 环境跳过 1**，退出码 0；内核断言 **73 项全通过**。

### 本轮实际改动清单（P0 → P2）

| 文件 | 改动 | 性质 |
|---|---|---|
| `core/kernel/`（6 文件） | 新增：`disposable` / `events` / `context` / `loader` / `registry` / `fiber_model.json` | 新增 |
| `core/registries.py` | 新增：进程默认 context + 四张注册表 + `EngineKind` | 新增 |
| `tools/run_tests.py` | 新增：统一门禁入口（PASS / FAIL / ENV-SKIP 三分类） | 新增 |
| `tools/kernel_demo.py` | 新增：七个痛点的前后对比演示 | 新增 |
| `test/test_kernel.py` | 新增：73 项断言（含自举一致性、源码级反回归门禁） | 新增 |
| `core/state_machine.py` | 注册表外移；**守卫解析改 fail-closed**（修真实缺陷） | 修复 |
| `core/hierarchical_state_machine.py` | 注册表顶部导入（解开循环依赖）；**动作异常不再静默吞掉** | 修复 |
| `core/engine_adapters.py` | 两张硬编码表 → `register_engine()`；`build_adapter` 错误可操作 | 收编 |
| `core/plugin.py` | 重写为注册表门面；**插件导入失败不再静默跳过** | 收编+修复 |
| `core/orchestrator.py` | 总线接内核；**修 `reset()` 泄漏监听器**；新增 `engine/step` 扩展点 | 修复+增强 |
| `core/analysis.py` | 新增 `SUPPORTED_KINDS` 能力声明；不支持时 **fail-loud** | 增强 |
| `engine/progress_bar.py` | tkinter 改**延迟导入**（使无头测试可运行） | 修复 |
| `web/server.py` | **5 处**重复映射 → `_engine_catalog()` 派生 | 收编 |
| `ui/application.py` | **7 处**段名字面量 → `_sec()`；Tab 装配改数据驱动 | 收编 |
| `ui/analysis_tab.py` / `ui/visualization_tab.py` | 硬编码列表 → 注册表派生 | 收编 |
| `core/plugins/{decision_table,llm_agent}.py` | 改用 `section=` 声明，去掉绕圈 lambda | 简化 |
| `README.md` | 测试命令与目录结构更新 | 文档 |
| `test/test_web_e2e.py` | 缺前端产物时以退出码 77 声明 ENV-SKIP | 治理 |

**净效果**：消除 6 处模块级全局状态；消除 **9 处**重复的 kind→段名 映射（原估算 3 处，实际更多）；修复 **7 个真实缺陷**（守卫 fail-open、编排器 `reset()` 监听器泄漏、插件 import 静默吞掉、config 读取静默为空、HSM 动作异常被吞、Tk9 `trace` 弃用、load 期 transition 校验缺失）；新增可拦截的引擎扩展点。

---

## 0. 核心论点：识别同构

### 0.1 第一层同构：Cordis Fiber 就是一个状态机

`vendor/cordis/src/fiber.ts` 的 `Fiber` 不是"有点像状态机"，它就是一个完整的、带守卫与进入/退出动作的状态机：

| 状态机概念 | 本项目 `state_machine.py` | Cordis `Fiber` | 源码位置 |
|---|---|---|---|
| 状态集 | `states` | `PENDING / LOADING / ACTIVE / FAILED / DISPOSED / UNLOADING` | `fiber.ts:147-154` |
| 转移事件 | `transitions` 的 key（`start`/`complete`…） | 依赖服务的 `provide` / 撤销、配置 `update`、显式 `dispose` | `reflect.ts:314-336`、`fiber.ts:736-753` |
| **转移守卫 guard** | `{"target": "run", "guard": "allow_go"}` | **`epoch` 指纹**：`inject` 集合中每个 provider 的 fiber uid 拼接 | `fiber.ts:611-623` |
| 守卫拒绝 | `(None, "Guard [x] 条件不满足")` | epoch 为 `INACTIVE` → 停在 PENDING，不执行 | `fiber.ts:625-639` |
| **on_enter 动作** | `on_enter` 字段 | `_reload()`：重新解析配置 + 执行插件主体 | `fiber.ts:646-673` |
| **on_exit 动作** | `on_exit` 字段 | `_unload()` + effect 逆序回收 | `fiber.ts:675-696` |
| 历史状态 | HSM 的 `history: "shallow"` | HMR 失败时回滚缓存并重挂旧插件 | `vendor/README.md:9` |
| 实例级守卫覆盖 | `guards=` 参数 | `isolate()` / realm | `state_machine.py:57-60` |

**这个对照表不是修辞。** 它意味着两件很实际的事：

1. **Cordis 的运行时内核，是项目 FSM 引擎的一个实例。** 因此内核的行为可以被项目的"可视化 Tab"渲染、被"分析 Tab"统计、被项目的守卫机制校验——零新增基础设施。
2. **反过来，Cordis 给了项目一个组件模型。** 状态机不再只是"七种被展示的范式之一"，而是**运行时的调度器本身**。

### 0.2 第二层同构：依赖失效 ≡ 项目自己的差分机

`core/difference_engine.py:16-19` 的自述原文：

> `StateDiff / ReactiveTracker`（状态差量 / 响应式追踪）—— 比较前后两次状态快照，产出「差分」(added / removed / changed)。**仅当差量命中订阅的键时触发回调**——一种轻量、确定性的「响应式 / 脏检查」，**避免对整棵状态树盲目重算**。
>
> 适用场景：… **配置热更新：仅对变更字段做处理。**

而 Cordis 的 epoch 机制做的是完全相同的事：

> `_refresh()` 遍历每个 `inject` 名，拼出 `':' + impl.fiber.uid`。任一依赖缺失即 `INACTIVE`。provider 的上线/下线**不需要为每个依赖存订阅关系**——只要重算指纹就能触发正确的 reload/unload。（`fiber.ts:611-623`）

**两者都是"以身份指纹代替全量重算"。** 项目已经把失效引擎写好了，只是用在"进度预测"和"UI 重绘"上，没用在它最该用的地方——**依赖解析**。

这给了一条具体的落地路径：原型里我们用朴素的 `_recheck()` 遍历（规模小，代价可接受）。一旦插件数量上升到数百，把 `_recheck()` 换成 `ReactiveTracker`，就得到 Cordis 的 epoch 语义，且**复用项目自己的代码与测试**。

### 0.3 第三层同构：项目已经具备 Cordis 的四分之三

这是最关键的发现。逐项比对：

| Cordis 基石 | 本项目已有的对应物 | 缺什么 |
|---|---|---|
| **Service Definition** | `core/engine_base.py:113` 的 `Engine` Protocol + `BaseAdapter`（`:127`） | 没有 Context 来承载"按名解析服务" |
| **Events**（类型化事件） | `core/orchestrator.py:26` 的 `EventBus`（含 `*` 通配订阅） | ① `subscribe()` 返回 `None`，**无退订**；② 只有一种派发模式 |
| **守卫 / 动作注册表** | `core/state_machine.py:11,25` 的 `GUARD_REGISTRY` / `ACTION_REGISTRY` | 全局可变、**注册不可撤销**、无作用域 |
| **插件注册表** | `core/plugin.py:46` 的 `PluginRegistry` + `discover()` | class-level 全局字典，无生命周期 |
| **配置（单一数据源）** | `config.json` + `web/orchestrations.json` | 单文件读取，**无分层、无校验、无 patch** |
| **Context（服务容器）** | **缺失** | ← 唯一真正缺的那一块 |

所以重构的准确描述是：

> **补上 `Context` 这一块拼图，并把四块拼图之间的接线从"单向"改成"可逆"。**

而不是"引入一个新框架"。

### 0.4 一个佐证：项目自己已经在手写 scope

`core/state_machine.py:57-60`：

```python
# 守卫函数表：实例级 guards 优先，其次全局 GUARD_REGISTRY
self.guards = dict(GUARD_REGISTRY)          # ← 构造时快照全局表
if isinstance(guards, dict):
    self.guards.update(guards)              # ← 实例级覆盖
```

这是 **scope（作用域覆盖）概念的雏形**——项目作者已经感觉到"全局注册表不够用，需要实例级覆盖"。但这个手写版本有三个限制：

1. **只覆盖了 guards 一处**；`ACTION_REGISTRY`、`_ADAPTERS`、`PluginRegistry` 都没有；
2. **是"构造时快照拷贝"**：实例创建后全局表新增的 guard 不会生效；
3. **无法撤销**：没有卸载语义。

Cordis 的 `ctx.provide` + `isolate` 正是这个需求的通用解。**项目已经用最朴素的方式表达了需求，重构只是把答案换成通用版。**

---

## 1. 现状盘点：四处全局状态 + 三类静默降级

### 1.1 模块级可变状态（6 处）

| # | 位置 | 内容 | 后果 |
|---|---|---|---|
| 1 | `core/state_machine.py:11` | `GUARD_REGISTRY: dict = {}` | 全局守卫表，无撤销 |
| 2 | `core/state_machine.py:25` | `ACTION_REGISTRY: dict = {}` | 全局动作表，无撤销 |
| 3 | `core/engine_adapters.py:403` | `_ADAPTERS = {...}` | 硬编码 kind → 适配器类 |
| 4 | `core/engine_adapters.py:413` | `_SECTION_OF = {...}` | 硬编码 kind → config 段名 |
| 5 | `core/plugin.py:47` | `PluginRegistry._plugins` | class-level 字典，跨实例共享 |
| 6 | `web/server.py` | `ORCH` 全局 dict | 同一时刻每个编排只能一份状态 |

### 1.2 重复的映射（新增范式必然漏改一处）

同一份「kind → config 段名」映射在**三个地方**各写了一遍：

- `core/engine_adapters.py:413` 的 `_SECTION_OF`
- `web/server.py:325-334` 的 `kinds` 字典（8 项）
- `ui/application.py:890-916` 的 7 个 Tab 注册

**具体后果**：加一个新范式（如 `decision_table`）时，`core/plugins/decision_table.py` 只暴露 `PLUGIN`，UI 侧靠 `ui/plugin_tab.py` 的泛化 Tab 兜住了，但 `web/server.py` 的 `api/engines` 端点需要单独追加 `cat.setdefault(pl.kind, ...)` 的补丁逻辑才不出错（`web/server.py:336-341`）——**这正是重复映射的代价**。

### 1.3 静默降级（应该 fail loud 的地方）

```python
# core/plugin.py:74-77  —— 插件导入失败被完全吞掉
for mod in pkgutil.iter_modules(pkg.__path__, package_name + "."):
    try:
        m = importlib.import_module(mod.name)
    except Exception:
        continue                    # ← 插件写错了？静默跳过，没有任何输出

# core/plugin.py:90-94  —— 配置读取失败被吞成空字典
def _provider():
    try:
        return load_config().get(section, {})
    except Exception:
        return {}                   # ← 配置坏了？表现为"这个范式没有实例"
```

用户看到的现象是"我写的插件没出现"，而系统没有任何提示。

### 1.4 实测发现的具体缺陷（本次验证）

| 缺陷 | 复现 | 影响 |
|---|---|---|
| **非法转移目标不在 load 期校验** | `{"transitions": {"go": "NOT_EXIST"}}` → 构造成功，首次 `trigger("go")` 抛裸 `KeyError('NOT_EXIST')`（`core/state_machine.py:127`） | 配置错误要到运行时才炸，且错误信息不含"哪台状态机的哪条转移" |
| **守卫不可撤销** | `register_guard("g1", fn)` 后无法注销 | 测试之间互相污染；无法为不同编排配置不同守卫集 |
| **事件无退订** | `EventBus.subscribe()` 返回 `None` | 编排重置（`Orchestrator.reset()`）只清 `engines`，**不清 `bus._subs`**——`configure()` 反复调用会累积重复监听器 |
| **无 per-编排隔离** | `web/server.py` 的全局 `ORCH` | 同一编排无法在进程内并存两份状态 |

> 第 3 条值得强调：`Orchestrator.reset()`（`core/orchestrator.py:114-117`）清空 `engines`、`trace`、`_bindings`，但**没有清 `self.bus`**。而 `configure()`（`:60-74`）每次都往 `bus` 里 `subscribe` 一批新 handler。所以反复 `configure` 同一编排会**线性累积监听器**——这是一个真实的 bug，且只有引入"注册即 effect"才能系统性消除。

---

## 2. 四档复用建议：该拿什么，该放什么

### A 档 · 必做（高价值、低风险、已验证）

| # | 复用项 | 解决的现状 | 原型对应 |
|---|---|---|---|
| **A1** | **effect / Disposable（注册即可逆）** | 4 处全局注册表无撤销；`reset()` 不清 bus | `disposable.py`（单次性 + 逆序回收） |
| **A2** | **Context 服务容器** | 6 处模块级全局状态 | `context.py`（`provide/get/require`） |
| **A3** | **inject 声明依赖** | 加载顺序靠代码顺序；provider 缺失时半死 | `context.py`（PENDING → ACTIVE） |
| **A4** | **事件派发模式 + 契约校验** | 只有同步广播；无拦截/改写/短路 | `events.py`（`emit`/`waterfall`/`serial`） |

这四项合起来直接消除 §1.1 的全部 6 处全局状态，并顺手修掉 §1.4 的第 3、4 条。

### B 档 · 建议做（价值明确，需要一次设计决策）

| # | 复用项 | 解决的现状 | 备注 |
|---|---|---|---|
| **B1** | **空根 + 分层 patch** | 单文件 config；内置 demo 不可覆盖 | 最小侵入方案：保留 `config.json`，新增顶层 `"patches": [...]` 段 |
| **B2** | **fail-loud 分层**（必败清单 / 可选行 / 点名文件） | §1.3 两类静默降级；§1.4 非法 target | 见 §4 P4 的验收断言 |
| **B3** | **自省接口**（`list_services` / `list_engines` / `list_bindings`） | UI 7 个硬编码 Tab；web 重复映射 | 这是"去硬编码"的唯一途径 |
| **B4** | **运行时不变式（`invariants.py` 伴生）** | 3 个测试文件靠人肉覆盖 | 见 §7 |
| **B5** | **isolate 作用域**（简化版） | 全局 `ORCH`；`state_machine.py:57-60` 的手写快照 | 原型已实现，兄弟作用域互不影响 |

### C 档 · 可选（视产品方向决定）

| # | 复用项 | 何时值得做 |
|---|---|---|
| **C1** | **自省能力暴露给 LLM Agent**（对应 `ui-cordis` 的 `cordis_inspect_*`） | 若要强化 `core/plugins/llm_agent.py`，让它能查询运行时目录 → 这是"AI 编排编排器"的前置能力 |
| **C2** | **config-only 热更新** | 若要"改配置不重启 UI"。注意原型的 `hot_reload` 会重建插件实例，**运行中状态必须外移到宿主服务** |
| **C3** | **用 `ReactiveTracker` 替换 `_recheck()`** | 插件数上到数百、`_recheck` 出现性能问题（当前规模完全不必要） |

### D 档 · 不要移植（明确劝退）

| 项 | 为什么不要 |
|---|---|
| **Proxy + trap 实现的 Context** | Python 的 `__getattr__` 达到同样效果，可读性更好、无 Proxy 帧污染栈追踪 |
| **6 态 fiber + LOADING/UNLOADING 过渡态** | 本项目无异步、无并发 reload；三态（PENDING/ACTIVE/FAILED）+ DISPOSED 已足够 |
| **epoch 字符串指纹** | 用 `ReactiveTracker` 或朴素 `_recheck` 即可；字符串拼接指纹是 TS 侧为规避订阅关系的取舍 |
| **模块级 HMR（`loadCache` + 依赖图分析）** | Cordis 侧依赖 Node `--expose-internals`，且 `vendor/README.md:19` 记录了真实事故。本项目热更的是**配置**不是模块 |
| **Typert / RPC 类型图 / `RemoteResult`** | Python 无对应工具链；本项目是单进程 |
| **vendored 框架层 + rescope + 21 条加固清单** | 本项目没有上游要 pin；那 21 条是"fork 别人框架"的代价，不是收益 |
| **双 SDK 投影同步那套流程** | 本项目只有一个 Python 载体 |
| **`!!js` 表达式做条件装配** | Python 环境下 `eval` 的收益远小于风险；直接写条件函数更清楚 |

---

## 3. 自举：用项目自己的引擎验证内核（已实现）

这是本方案区别于"普通框架移植建议"的地方。

### 3.1 做法

`core/kernel/fiber_model.json` —— 用项目**自己的状态机配置格式**描述 Cordis Fiber 的生命周期：

```json
{
  "type": "flat",
  "initial": "PENDING",
  "description": "Cordis Fiber 生命周期（内核的自模型）",
  "states": {
    "PENDING": {
      "content": "已挂载；inject 未满足或尚未求值；apply 尚未执行",
      "on_enter": "join_pending_list",
      "on_exit": "leave_pending_list",
      "transitions": {
        "provide":       { "target": "ACTIVE", "guard": "inject_satisfied" },
        "provide_error": "FAILED",
        "dispose":       "DISPOSED"
      }
    },
    "ACTIVE": {
      "content": "apply 已执行；持有 N 个 effect",
      "on_enter": "run_apply",
      "on_exit": "unwind_effects",
      "transitions": { "unprovide": "PENDING", "dispose": "DISPOSED" }
    },
    "FAILED": {
      "content": "apply 抛错；本次收集的 effect 已全部回滚",
      "on_enter": "rollback_effects",
      "transitions": { "unprovide": "PENDING", "dispose": "DISPOSED" }
    },
    "DISPOSED": { "content": "已卸载；effect 逆序回收完毕，服务清空", "transitions": {} }
  }
}
```

**格式的合法性已由项目引擎亲自确认**：测试里 `create_state_machine("fiber", full_cfg)` 成功构造实例，`guard` 与 `on_enter` / `on_exit` 都走项目自己的解析路径。

### 3.2 验证方式：锁步一致性

`test/test_kernel.py` 的 `[9] 自举一致性` 组：

```
每个操作 → ① 执行真实内核操作  ② 向模型发送对应事件  ③ 断言两者状态一致
```

已通过的 5 个场景：

| 场景 | 覆盖 |
|---|---|
| **A** 正常插件 | `PENDING→ACTIVE→PENDING→ACTIVE→DISPOSED` 逐步一致（含"先挂载后提供"的逆序） |
| **B** apply 抛错 | `PENDING→FAILED→PENDING→FAILED→DISPOSED` 一致 |
| **C** 双向校验 | 模型**未声明**的转移，内核同样不得发生（`PENDING` 上 `unprovide` 两侧都不动） |
| **D** 动作可观测 | 模型的 `on_enter`/`on_exit` 是真实 `ACTION_REGISTRY` 动作，`run_apply` 确实执行 |
| **E** 格式合法性 | 配置可被项目 FSM 引擎直接加载 |

### 3.3 这样做换来什么

1. **最强的一致性测试**：内核实现与它的模型不可能悄悄漂移。任何一侧改了转移条件，测试立刻变红。（事实上这组测试在开发中当场抓出了我自己的两处场景错误。）
2. **可视化零成本**：这张图是 `Graph` 可直接渲染的——加一个"内核"Tab 就能看到项目自己的运行时状态迁移。
3. **可被项目的守卫机制约束**：如"`DISPOSED` 不得有出边"这类规则，可以写成 `ctx.guards` 里的守卫并自动校验。
4. **概念统一**：项目对外宣称"多范式决策引擎"，现在**它自己也成了一个可被展示的范式**——这对一份教学型/演示型项目是很有说服力的收束。

---

## 4. 分阶段落地（P0–P4）

每一阶段都**独立可验收、可回退**，且优先采用"绞杀者模式"（旧 API 保留为薄包装一个版本周期）。

### P0 · 建立内核骨架（不动任何现有代码）

- 新增 `core/kernel/`（`disposable.py` / `events.py` / `context.py` / `loader.py`），直接采用 `core/kernel/`。
- 新增 `test_kernel.py`（48 项断言，含自举一致性）。
- **验收**：`python test_kernel.py` 退出码 0；`python demo.py` 退出码 0。
- **风险**：无（纯新增）。

### P1 · 收编四处全局注册表

| 旧 | 新 | 兼容层 |
|---|---|---|
| `GUARD_REGISTRY` / `ACTION_REGISTRY` | `ctx.guards` / `ctx.actions` | `register_guard(name, fn)` 保留，转发到进程默认 ctx 并返回 `Disposable` |
| `_ADAPTERS` / `_SECTION_OF` | `ctx.engines.register(kind, cls, section, label)` | `build_adapter()` 保留，转发查询 `ctx.engines` |
| `PluginRegistry._plugins` | `ctx.plugins` | `PluginRegistry.register/get/all` 保留为薄包装 |
| `web/server.py` 的 `ORCH` | 每个编排一个 `ctx.isolate()` 作用域 | 模块级 `ORCH` 改为 `dict[str, Context]` |

- **验收断言**：
  1. `dispose()` 后 `ctx.services()`、`ctx.mount_states()`、事件监听器数全为 0；
  2. 同一进程内建两个 `Orchestrator`，各自的引擎实例 `is not` 另一个，且卸载 A 不影响 B；
  3. **回归修复**：连续 `configure()` 同一编排 N 次，`bus` 监听器数保持常量（当前是线性累积）。
- **风险**：中。旧 API 的语义差异（返回值从 `None` 变为 `Disposable`）需逐个确认调用方。

### P2 · 事件升级

- `EventBus` 增加 `on()`（返回 `Disposable`）/ `waterfall()` / `serial()`，保留 `subscribe()` 作为 `on()` 的别名。
- 为引擎 step 引入两个扩展点（这是**产品价值**，不只是架构）：`engine/step`（waterfall，可改写入参/否决）与 `engine/stepped`（emit，纯通知）。
- **验收断言**：
  1. `on()` 返回的句柄 `dispose()` 后监听器数减 1；
  2. 同一事件名混用派发模式立即抛错；
  3. 一个"输入钳制"策略插件能在不改 `Orchestrator` 的前提下把非法 `ctx.event` 改写掉。
- **风险**：低。新增能力，不改变既有行为。

### P3 · 配置分层（最小侵入）

保留 `config.json` 作为**唯一数据源**，但新增顶层 `"patches"` 段，并让 `load_config()` 返回 patch 后的结果：

```json
{
  "state_machines": { "...": "内置 demo，不改" },
  "orchestration": { "...": "内置编排，不改" },
  "patches": [
    { "insert": [ { "id": "user-demo", "name": "orchestration.user", "config": { "...": "..." } } ] },
    { "id": "SM_Init", "config": { "states": { "...": "整体替换" } } }
  ]
}
```

- **验收断言**：
  1. patch 目标缺失 / `name` 不匹配时**只警告不抛错**，且不误改其它行；
  2. `apply_patches(base, patches)` **不修改入参**（这是热重载可回退的前提）；
  3. 同一组 patch 重放 3 次结果完全一致。
- **风险**：中。整键替换的语义必须写进 README——用户改一个字段要重述该 `config` 块的全部字段。

### P4 · fail-loud 分层 + 自省 + 门禁

**四类失败必须区别对待**（这是报告里最有操作性的结论之一）：

| 类别 | 例子 | 正确行为 |
|---|---|---|
| **必败** | 核心引擎段缺失、内置编排的引擎引用不存在 | 立刻抛错并中止 |
| **可选行** | 某个可选范式未安装 | 警告 + 跳过，不影响其余 |
| **点名文件缺失** | 用户显式 `--patch foo.json` 但文件不存在 | **抛错**（调用方点名了它） |
| **未注册的插件** | `core/plugins/` 下某个文件 import 失败 | **抛出带文件名的 ImportError**（当前是 `except Exception: continue`） |

**新增 load 期校验**（修掉 §1.4 第 1 条）：遍历全部 `states` 与 `transitions`，断言每个 `target` 存在、`initial` 存在、`guard` 名已注册。给出精确定位：

```
SM_Init.states.idle.transitions.go → 目标 "NOT_EXIST" 不存在
```

**自省接口**：

```python
ctx.inspect.engines()     # [{kind, label, section, instances:[...]}]
ctx.inspect.services()    # 当前 ctx 可见服务
ctx.inspect.bindings()    # 编排绑定（含"when 的 etype 无人发出"这类可疑项）
ctx.inspect.pending()     # 停在 PENDING 的插件 —— 排查"插件静默不生效"的确定入口
```

然后 `ui/application.py` 的 7 个硬编码 Tab 与 `web/server.py:325-334` 的重复 `kinds` 字典**全部改为遍历自省结果**。

- **验收断言**：
  1. 构造一份含非法 target 的配置 → **load 期**抛出带定位信息的错误；
  2. `core/plugins/` 下放一个语法错误的 `*.py` → 抛出带文件名的错误（而非静默跳过）；
  3. 新增一个范式只需 `ctx.engines.register(...)`，UI 与新 Web 端点自动出现（无任何硬编码改动）。
- **风险**：低–中。校验可能对现有配置报出既有问题（属于收益）。

---

## 5. 逐文件改造清单

| 文件 | 现状 | 改为 | 阶段 | 风险 |
|---|---|---|---|---|
| `core/kernel/*` | — | 新增（原型可直接搬） | P0 | 无 |
| `test_kernel.py` | — | 新增 48 项断言 | P0 | 无 |
| `core/state_machine.py:11,25` | 全局 `GUARD_REGISTRY`/`ACTION_REGISTRY` | `ctx.guards`/`ctx.actions`；旧函数转发 | P1 | 中 |
| `core/state_machine.py:57-60` | `dict(GUARD_REGISTRY)` 快照 | `ctx.isolate()` + 服务解析 | P1 | 低 |
| `core/state_machine.py:127` | 裸 `KeyError` | load 期校验 + 精确定位 | P4 | 低 |
| `core/engine_adapters.py:403,413` | `_ADAPTERS` / `_SECTION_OF` | `ctx.engines` 注册表 | P1 | 中 |
| `core/engine_adapters.py:428` | `build_adapter()` 直查字典 | 转发 `ctx.engines.build()` | P1 | 低 |
| `core/plugin.py:47` | class-level `_plugins` | `ctx.plugins` | P1 | 中 |
| `core/plugin.py:76-77` | `except Exception: continue` | 带文件名抛错 | P4 | 低 |
| `core/plugin.py:90-94` | `except Exception: return {}` | 区分"段不存在"与"读取失败" | P4 | 低 |
| `core/orchestrator.py:26` | `EventBus.subscribe` 返回 `None` | `on()` 返回 `Disposable`；加三模式 | P2 | 低 |
| `core/orchestrator.py:114-117` | `reset()` 不清 `bus` | 依赖 effect 自动回收 | P1 | 低 |
| `core/config.py:7` | 单文件 `json.load` | `load_config()` → `apply_patches()` | P3 | 中 |
| `web/server.py:325-334` | 硬编码 `kinds` 字典 | 遍历 `ctx.inspect.engines()` | P4 | 低 |
| `web/server.py` 全局 `ORCH` | 单一状态 | `dict[str, Context]` | P1 | 中 |
| `ui/application.py:890-916` | 7 个硬编码 Tab | 遍历自省结果生成 | P4 | 中 |
| `ui/plugin_tab.py` | 泛化 Tab（已很好） | 成为**唯一**的 Tab 渲染器 | P4 | 低 |
| `core/plugins/*.py` | `PLUGIN = EnginePlugin(...)` | 保持；额外支持 `inject` 字段 | P1 | 低 |

---

## 6. 收益量化

**消除的全局状态**：6 处（§1.1 全部）

**删除的重复代码**：

| 位置 | 行数 |
|---|---|
| `ui/application.py:890-916` 的硬编码 Tab 注册 | ≈ 27 |
| `web/server.py:325-334` 的 `kinds` 字典 | ≈ 10 |
| `core/engine_adapters.py:413` 的 `_SECTION_OF` | ≈ 12 |
| 合计 | **≈ 49 行**（且是"新增范式必须同步改"的那类行） |

**新增能力**（都是当前完全没有的）：

1. 注册可撤销（修掉 `reset()` 不清 bus 的真实 bug）
2. 依赖驱动的加载顺序（配置行序不再影响结果）
3. 策略拦截（限流/审计/输入钳制/缓存可作为插件挂上，不必改 `Orchestrator`）
4. 编排级隔离（并发驱动、单独卸载）
5. 配置分层（内置 demo 可被用户覆盖而不修改内置文件）
6. 自省（UI 与 Web 去硬编码的唯一途径）
7. 可执行不变式（§7）

**新增的确定性**（这是最容易被低估的收益）：`ctx.inspect.pending()` 让"插件为什么没生效"从"读代码推断"变成"查一个列表"。

---

## 7. 验收：不变式与门禁

对应研究报告「把不可靠的判断下沉为机器门禁」那一章。建议新增 `tools/check.py` 作为**唯一 gate 入口**，聚合以下检查：

| # | gate | 检查什么 | 现状 |
|---|---|---|---|
| G1 | 内核断言 | `test/test_kernel.py` 的 48 项 | 已有 |
| G2 | 自举一致性 | 内核状态与 `fiber_model.json` 锁步一致 | 已有 |
| G3 | 配置 Schema | 每个 `states`/`transitions.target`/`initial`/`guard` 名合法且存在 | 内核已保证（`core/state_machine.py` load 期校验） |
| G4 | 重复注册检测 | 同一 ctx 内重复 `provide` / 重复 `register(kind)` 报错 | 内核已保证 |
| G5 | 无泄漏 | 每个 demo/测试结束后 `effect_count()==0`、服务为空、监听器为 0 | 内核已保证 |
| G6 | patch 重放确定性 | 同一 patch 重放 3 次结果相同、入参未被修改 | 内核已保证 |
| G7 | 静默降级检测 | 全仓 grep `except Exception:` 后紧跟 `continue`/`return {}` 的位置，人工确认为"有意的降级" | 待做 |
| G8 | 插件可发现性 | `core/plugins/` 下每个 `*.py` 都能被 import（防止插件静默失效） | 待做（P4） |

**每模块 `invariants.py`** 的设计（对应报告的 39 个 `./invariant` 伴生包）：

```
core/state_machine.py   → core/invariants/state_machine.py   断言：当前状态必在 states 中；history 的 from/to 均合法
core/orchestrator.py    → core/invariants/orchestrator.py    断言：每个 binding 的 when.etype 有人发出；engines 非空
core/kernel/context.py  → core/invariants/kernel.py          断言：ACTIVE 插件的 inject 全部可解析（原型已有此断言）
```

报告的规则值得直接照抄：**"只有独立观测可能发散时才写不变式；空检查/只查服务存在性的检查一律非法。"**

---

## 8. 研究报告的哪些结论可直接用 / 哪些不适用

| 报告结论 | 本项目适用性 | 落地形式 |
|---|---|---|
| "一切皆插件"：注册即 effect，卸载即回收 | ✅ **直接适用**（A1） | `ctx.effect()` / `Disposable` |
| Context 是服务仓库，插件按 key 查找 | ✅ **直接适用**（A2） | `ctx.provide/get` + `__getattr__` |
| `inject` 声明依赖，加载顺序由服务可得性决定 | ✅ **直接适用**（A3） | PENDING → ACTIVE |
| 五种派发模式，模式是公开契约 | ⚠️ **部分适用**：只需 `emit`/`waterfall`/`serial` 三种；`parallel`/`bail` 本项目无并发场景 | `events.py` |
| Waterfall 是 around-middleware，不调 `next()` 即短路 | ✅ **直接适用** | 策略插件 |
| 空根 + 分层 patch；按 id 整键替换；patch 不跨 include 边界 | ✅ 适用（B1）。"不跨 include"本项目无 include 概念，可忽略 | `apply_patches` |
| patch 算法单一纯函数，挂载与离线 dump 共用 | ✅ **直接适用** | `core/kernel/loader.py` |
| fail-loud 分层（必败 / 可选 / 点名文件） | ✅ **直接适用**（B2） | P4 |
| "Model-visible ⟺ logged" 可执行断言 | ✅ **思想适用**：本项目对应物是"**引擎状态必须可由事件轨迹重建**" | G2 自举一致性 + `trace` 校验 |
| 运行时不变式（`invariant.ts` 伴生） | ✅ 适用（B4） | `core/invariants/` |
| capability seam 三角色（Definition/Provider/Consumer） | ✅ **已经具备**（`Engine`/`BaseAdapter`/插件） | 只差显式化命名 |
| 自省工具（`cordis_inspect_*`）暴露给 agent | ⚠️ 可选（C1）；见下 | `ctx.inspect` |
| postmortem 必须产出机器可执行 guardrail | ✅ 适用（文化层） | `tools/check.py` |
| vendor 框架的 21 条本地加固 | ❌ **不适用**：那是 fork 别人框架的代价 | — |
| 双 SDK 投影同步 | ❌ 不适用 | — |
| Proxy/trap、6 态 fiber、epoch 字符串指纹 | ❌ 不适用（D 档） | — |
| Typert / RPC 类型图 / 桌面端 / 多端载体 | ❌ 不适用（单进程 Python） | — |

**一条特别值得展开**：报告里的 `ui-cordis` 让 agent **读自己的运行时目录**（`cordis_inspect_list/query`：Service / Event / Builtin / Tool / Slots / Theme）并**写一个临时插件挂上去**（`define/run/stop/undefine`）。

本项目有一个天然的对应物：`core/plugins/llm_agent.py`（LLM 智能体范式）。一旦有了 `ctx.inspect`，就可以让 LLM agent：

1. 查询"当前有哪些引擎、哪些编排、哪些绑定、哪些绑定指向了不存在的引擎"；
2. **生成一份编排配置并用 patch 层加载**（而不是写代码）——因为配置是数据，这是安全的；
3. 在沙箱里 `define` 一个临时插件做实验，失败就 `undefine`。

这比"让 LLM 写 Python 代码"安全一个数量级，而且**正是 Cordis 的 `ui-cordis` 信任模型的翻版**：持久化必须走受审批的安装路径，运行时试验则限制在可回收的作用域内。

报告的这条警告同样适用：**动态代码执行不是安全边界**。若要做 C1，必须像 Cordis 那样在 README 里明说"把动态插件当作 bash 权限对待"，并把持久化路径单独收窄。

---

## 9. 风险与回退

| 风险 | 等级 | 缓解 |
|---|---|---|
| 整键替换的语义反直觉（改一字段要重述整个 config 块） | **中高** | 必须在 README + `config.json` 注释里显式说明；提供 `--dump-config` 等价物让用户看到合成结果 |
| 旧 API 返回值变化（`None` → `Disposable`）破坏调用方 | 中 | 保留旧函数为薄包装一个版本周期；`None` 返回值的调用方不受影响 |
| 引入 `ctx` 后调试栈变长（多一层 `__getattr__`） | 低 | `__getattr__` 只在服务缺失时抛错，且错误信息列出可用服务 |
| `_recheck()` 全量遍历的 O(n²) 风险 | 低（当前 n<50） | 留好替换为 `ReactiveTracker` 的接口；`_recheck` 已是 `Context` 的私有方法，替换不动调用方 |
| 自举一致性测试成为"改内核就要改模型"的负担 | 低 | 这正是它的目的——**模型与实现必须同步演进**；且模型只有 4 个状态 |
| 过度设计（给 6,660 行的项目引入企业级框架） | **中** | 本方案已明确 D 档劝退 8 项；内核 4 个文件合计 **966 行**（含约六成注释与文档），约占项目规模 15% |

**回退路径**：P0 是纯新增，删除 `core/kernel/` 即完全回退。P1–P4 每个阶段独立，旧 API 在 P1–P3 期间始终可用，可随时停止推进而保持系统可运行。

---

## 10. 落位状态、证据与局限

> 本节记录**实际已完成**的部分，而非设计意图。原 `prototype/` 目录已删除——
> 其内容全部迁入项目的规范位置（`core/kernel/`、`test/`、`tools/`），
> 避免出现"两处都可以改"的漂移风险。

### 10.1 可运行方式

```bash
cd zhuangtaiji
python tools/run_tests.py            # 门禁总入口（推荐）
python tools/run_tests.py kernel     # 只跑内核断言（48 项）
python tools/kernel_demo.py          # 七个痛点的前后对比演示
```

### 10.2 落位的交付物

| 路径 | 内容 | 阶段 |
|---|---|---|
| `core/kernel/disposable.py` | `Disposable`（单次性、可 join）/ `DisposableList`（逆序回收） | P0 |
| `core/kernel/events.py` | `EventBus`：`emit`/`waterfall`/`serial` + 派发模式契约校验 | P0 |
| `core/kernel/context.py` | `Context`：服务容器、`effect`、`plugin`、`isolate`、生命周期转移 | P0 |
| `core/kernel/loader.py` | `apply_patches` / `compose` / `Loader` / `hot_reload` / 必败清单审计 | P0 |
| `core/kernel/registry.py` | `Registry`：可撤销、fail-loud、可自省的通用注册表 | P0 |
| `core/kernel/fiber_model.json` | 用项目配置格式描述的内核生命周期自模型 | P0 |
| `test/test_kernel.py` | 48 项断言（含自举一致性 5 场景） | P0 |
| `tools/run_tests.py` | 测试与门禁统一入口（区分 PASS / FAIL / ENV-SKIP） | P0 |
| `tools/kernel_demo.py` | 七个痛点的前后对比演示 | P0 |
| `tools/build_doc.mjs` | 本方案 Markdown → HTML 的构建脚本 | — |

### 10.3 已验证的事实（不是设计意图）

- **门禁全绿**：`python tools/run_tests.py` → 通过 3 / 失败 0 / 环境跳过 1，退出码 0。
- **48 项内核断言全部通过**（`通过 48 项，失败 0 项`），含自举一致性 5 场景。
- 内核状态与 `fiber_model.json` 在 5 个场景中逐步一致。
- `fiber_model.json` 可被项目自己的 `create_state_machine()` 直接加载，`guard` 与 `on_enter`/`on_exit` 走项目自己的解析路径。
- `effect` 的"注册即执行"语义在开发中**当场抓出**了我自己两处用法/场景错误——这是语义正确性的一个旁证。
- **`test_verify.py` 已从"无法运行"变为"通过"**（见 §10.5）。

### 10.4 局限（必须说明）

1. **内核是"够用即止"的实现，不是生产级框架**。没有并发、没有持久化、没有错误上报通道。
2. **不实现真实 HMR**。`hot_reload` 只是"dispose + 重算 patch + 重新挂载"，被重建的插件会丢失实例内状态——需要保留的状态必须外移到宿主服务。这**不等于** Cordis 的模块热重载。
3. **`_recheck()` 是朴素全量遍历**，不是 epoch/差分失效。规模上到数百插件时应替换为 `difference_engine.ReactiveTracker`。
4. **`isolate` 是简化版**：只做"同名服务在子树内独立解析 + 不穿透祖先"，没有 Cordis 的 delimiter 符号与 realm 引用计数 GC。
5. **本方案的收益量化基于静态阅读**，§6 的 49 行是可直接删除的重复代码，实际净变化取决于兼容层的写法。
6. **P1–P4 的收编尚未把旧调用方全部切换到 ctx**——旧 API 仍由薄包装提供，两条路径暂时并存。

### 10.5 P0 阶段顺带修掉的真实缺陷

改造前 P0 的基线探测（`python test/test_verify.py`）直接暴露了三个问题，本阶段一并修复：

| 缺陷 | 真相 | 修复 |
|---|---|---|
| README 写的测试路径全部过时 | `python test_verify.py` 实际是 `test/test_verify.py` | 修正 README（含目录结构段） |
| 从 `test/` 运行找不到 `core` | Python 把**脚本所在目录**而非 CWD 加入 `sys.path` | `tools/run_tests.py` 自动设置 `PYTHONPATH` |
| **`test_verify.py` 完全无法运行** | `engine/progress_bar.py:1` 顶层 `import tkinter`，而该文件只在 `:63` 用到 tkinter 一次；测试却只用纯缓动函数 | 改为**延迟导入**（`_require_tk()`），GUI 不可用时给出可操作错误；纯逻辑测试不再受牵连 |

第 3 条是典型的"GUI 依赖污染可测逻辑"：一个 GUI 导入让整个纯逻辑测试套件在无头环境直接崩掉。修复后 `test_verify.py` 从**无法运行**变为**全部通过**。

同时为"前置条件未就绪"建立了显式约定：`test/test_web_e2e.py` 在缺前端 `dist/` 时以退出码 **77** 退出，由 `run_tests.py` 归类为 `ENV-SKIP` 而非 `FAIL`——**把"环境没准备好"与"代码坏了"分开**，这是门禁可信度的前提。

---

## 附录 A：Cordis 概念 → 本项目命名的对照（拟采用）

| Cordis | 本项目建议命名 | 说明 |
|---|---|---|
| `Context` | `Context` | 保持一致，便于对照报告 |
| `ctx.effect()` | `ctx.effect()` | 保持 |
| `inject` | `inject` | 保持 |
| `provide` / `get` | `provide` / `get` / `require` | `require` 是"必须有"版本，错误信息更可操作 |
| `emit` / `waterfall` / `serial` | 同名 | 保持 |
| `Fiber` | （不引入该名） | 用 `Context` 的 `state` 属性承载，避免两套生命周期概念 |
| `isolate` / realm | `ctx.isolate()` | 简化版 |
| `bundle` / `profile` / patch | `patch` 层 | 只保留 patch，不引入 bundle/profile 两级 |
| `Loader` | `Loader` | 保持 |
| `invariant` | `core/invariants/*.py` | 伴生模块 |

## 附录 B：验证命令速查

```bash
# 内核原型自检
cd zhuangtaiji && python test/test_kernel.py

# 内核行为演示
cd zhuangtaiji && python tools/kernel_demo.py

# 项目原有测试（改造前先跑一遍作为基线）
python test_verify.py && python test_enhancements.py

# 自举模型单独验证
python -c "import sys; sys.path.insert(0,'.'); from core import create_state_machine; import json; m=json.load(open('core/kernel/fiber_model.json',encoding='utf-8')); print(create_state_machine('fiber', {'state_machines':{'fiber':m}}).current_state_id)"
```
