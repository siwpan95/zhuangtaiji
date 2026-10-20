# -*- coding: utf-8 -*-
"""配置加载：单文件直读 + 可选的分层 patches 叠加。

设计取舍（Cordis 范式的精简落地）
================================
Cordis 的"空根 + 分层 patch"在本项目对应为：``config.json`` 仍是单一真源，
但允许在其顶层加一个 ``patches`` 段，表达"在不修改内置 demo 的前提下覆盖/新增
实例"。这与原分析里 P3 的目标一致——也是 **C 档（可选）**，因此实现保持最小、
向后兼容、可测：

* ``config.json`` 没有 ``patches`` 段时，``load_config()`` 行为与改造前完全一致；
* 有 ``patches`` 段时，叠加是**纯函数**——不修改磁盘文件，每次都从磁盘重读基底，
  因此可重复热重载（P2 的 hot_reload 直接复用即可）；
* patch 目标（section / name）缺失只**警告并跳过**，不抛错（fail-soft，P4 的分层
  精神：配置问题不该让进程崩溃）；
* 入参不可变：有 patch 时深拷贝基底，避免把叠加结果烘焙进缓存；
* ``patches`` 是元数据，不会出现在返回的可用段里（装配前剥离）。

patch 两种形态
------------
* 覆盖：``{"section": "state_machines", "name": "SM_Init",
  "override": {"initial": "running"}}`` —— 整键替换 ``config[section][name]`` 下的
  顶层字段（**不**做字段级深合并：某字段最终由谁给只有一个答案）。
* 新增：``{"insert": {"section": "state_machines", "name": "SM_New",
  "spec": {...}}}`` —— 新增一个实例；若已存在则警告并跳过。
"""
import copy
import json
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path: str = None):
    """加载配置（默认项目根目录下的 ``config.json``）。

    :param path: 可选；指定其它配置文件路径（测试用）。默认用项目内 ``config.json``。
    :returns: 应用了 ``patches`` 段（若有）之后的配置 dict。
    """
    config_path = (os.path.join(_PROJECT_ROOT, "config.json")
                   if path is None else path)
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    if not isinstance(config, dict):
        return config
    patches = config.get("patches")
    if patches:
        config = apply_config_patches(config, patches)
    return config


def apply_config_patches(config: dict, patches, warn=print) -> dict:
    """把 ``patches`` 应用到 ``{section: {name: spec}}`` 结构的配置上，返回新 dict。

    详见模块 docstring 的 patch 形态与语义。

    :param config: 基底配置（不会被修改，内部深拷贝）。
    :param patches: patch 列表。
    :param warn: 诊断输出函数（默认 ``print``）。
    :returns: 叠加后、且已剥离 ``patches`` 元数据段的新配置。
    """
    data = copy.deepcopy(config)
    data.pop("patches", None)          # 元数据段不进入可用配置

    for patch in (patches or []):
        if not isinstance(patch, dict):
            warn(f"[config-patch] 非映射 patch，已跳过：{patch!r}")
            continue

        # ---- 新增实例 ----
        if "insert" in patch:
            ins = patch["insert"] or {}
            sec = ins.get("section")
            name = ins.get("name")
            if not sec or not name:
                warn(f"[config-patch] insert 缺少 section/name：{patch!r}")
                continue
            if not isinstance(data.get(sec), dict):
                warn(f"[config-patch] insert 目标段 {sec!r} 不存在，跳过")
                continue
            if name in data[sec]:
                warn(f"[config-patch] insert 实例 {sec}/{name} 已存在，跳过")
                continue
            data[sec][name] = copy.deepcopy(ins.get("spec", {}))
            continue

        # ---- 覆盖现有实例 ----
        sec = patch.get("section")
        name = patch.get("name")
        override = patch.get("override")
        if not sec or not name or not isinstance(override, dict):
            warn(f"[config-patch] override patch 缺少 section/name/override：{patch!r}")
            continue
        if not isinstance(data.get(sec), dict):
            warn(f"[config-patch] 目标段 {sec!r} 不存在，跳过")
            continue
        if name not in data[sec]:
            warn(f"[config-patch] 目标实例 {sec}/{name} 不存在，跳过")
            continue
        for key, value in override.items():
            data[sec][name][key] = copy.deepcopy(value)   # 整键替换，不深合并

    return data
