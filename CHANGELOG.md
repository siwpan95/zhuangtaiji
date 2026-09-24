# 更新日志（Changelog）

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。每个版本对应一个**注解 tag** 与一个
[Gitee Release](https://gitee.com/siwpan/zhuangtaiji/releases)，两边说明同源；**本文件是仓库内的
权威副本**，Release 正文与其一致。

| 版本 | 日期 | 绑定提交 | 摘要 |
|---|---|---|---|
| [v1.0.1](#v101--2026-09-24) | 2026-09-24 | `429710a` | Web 编排服务默认只绑定回环地址（安全修复） |
| [v1.0.0](#v100--2026-09-24) | 2026-09-24 | `10357b6` | Cordis 风格内核重构完成（P0–P4） |

---

## [v1.0.1] — 2026-09-24

> 承接 `v1.0.0` 的收尾补丁：把「仅本机可用」从**文档承诺**变成**默认行为**。
> tag `v1.0.1` → 提交 `429710a` · [Release](https://gitee.com/siwpan/zhuangtaiji/releases/tag/v1.0.1)

### 安全修复（本版唯一实质变更）

- **默认监听改为 `127.0.0.1`**：原实现绑定 `0.0.0.0`，而该服务**无鉴权**、响应头又是
  `Access-Control-Allow-Origin: *` —— 同网段任何人都能通过 `PUT` / `DELETE` /
  `POST /api/orchestration/*` 读、写、删你的编排；而 README 与控制台都只写 `localhost`，
  很容易被读成「仅本机」。
- **需要时显式放开**：新增 `--host <addr>` 参数与 `ZHUANGTAIJI_HOST` 环境变量，
  优先级 `命令行 --host` > `ZHUANGTAIJI_HOST` > `127.0.0.1`。
- **放开时给告警**：监听非回环地址时，控制台打印明确风险提示（无鉴权 + CORS 放开 + 同网段可读写删）。
- 用法：`python web/server.py [port] [--host <addr>]`；文档补「安全默认」段
  （`README.md` / `README.en.md`）与模块 docstring。

### 质量门禁（发布前实机复核）

- 统一门禁 `tools/run_tests.py`：**通过 6 / 失败 0 / 环境跳过 0**
- 死根路径门禁 `scan_hardcoded.ps1`：**0 命中**
- 真实冒烟（默认模式）：仅 `127.0.0.1:8011` 监听；`GET /` 与 `GET /api/orchestrations` 均 **200**；
  从局域网地址 `192.168.1.47:8011` 访问**连接被拒**；`stderr` 无告警；停止后无残留监听
- 参数解析：缺参 / 未知参数按用法报错退出；`--host=0.0.0.0` 与 `--host 0.0.0.0` 等价

### 变更面

`README.md` / `README.en.md` / `web/server.py`（+48 −4），单提交 `429710a`。

### 升级提示

若你此前依赖**从局域网其他机器**访问编排编辑器，升级后需显式开启：

```bash
python web/server.py 8011 --host 0.0.0.0
```

请先确认所在网络可信 —— 该服务没有鉴权，放开即成同网段可读写删。

---

## [v1.0.0] — 2026-09-24

> 首个正式里程碑。把原本散落在各模块的全局状态与重复映射，重组成 Cordis 内核式的
> 「服务容器 + 生命周期 + 事件总线」。
> tag `v1.0.0` → 提交 `10357b6` · [Release](https://gitee.com/siwpan/zhuangtaiji/releases/tag/v1.0.0)

### 核心改动

- **落位 `core/kernel/`**：`Context`（服务容器 + 生命周期 + `inject` 驱动挂载）、`EventBus`
  （emit / waterfall / serial 三派发模式）、`Loader`、注册表、`Disposable`、
  `fiber_model.json`（用项目自己的状态机配置格式做自举一致性锁步验证）
- **收编单一注册表来源**：`GUARD`/`ACTION` 注册表、`_ADAPTERS`/`_SECTION_OF` 引擎表、
  `PluginRegistry` 统一归并，消除 **9 处**重复的 `kind → 段名` 映射（含源码级反回归门禁）
- **配置分层 `patches` 段**：`apply_config_patches` 纯函数，整键替换 / 插入，目标缺失 fail-soft，
  入参不可变
- **P4 fail-loud**：修 7 处静默降级；load 期配置校验（非法 `initial`/`transition.target`
  带精确路径报错）；`Context.inspect` 自省接口（engines / services / bindings / pending）

### 质量门禁

- 统一门禁 `tools/run_tests.py`：内核 **80 项断言全过**，整体 **通过 5 / 失败 0 / 环境跳过 1**
  （跳过数取决于该机是否有带 `tkinter` 的解释器，门禁会自动探测备用解释器重试）
- UI 烟测在 Tk 9.0 上真实运行（看门狗硬杀退出被正确判为 PASS）

### 顺手修复的真实缺陷

- 守卫 fail-open → fail-closed
- `Orchestrator.reset()` 监听器泄漏
- 插件 import / config 读取静默吞掉
- HSM 动作异常被吞
- Tk9 `trace` 弃用

### 附：端口

- 服务端口登记为 **8011**（原默认 `8000` 与 radio-panel 冲突）
