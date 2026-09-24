# -*- coding: utf-8 -*-
"""P3 验证：配置分层 patches 段（core/config.py）。

覆盖点：
1. 无 patches 段时 load_config 行为与改造前一致（向后兼容）；
2. override 按整键替换生效，且基底不可变；
3. insert 新增实例生效；
4. 目标（section / name）缺失只警告、不抛错（fail-soft）；
5. 加载后 patches 元数据段被剥离，不污染可用配置。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import config as cfg_mod

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(label, fn):
    global _PASS, _FAIL
    try:
        fn()
        _PASS += 1
        print(f"  [ok]   {label}")
    except Exception as exc:
        _FAIL += 1
        import traceback
        _FAILURES.append((label, exc, traceback.format_exc()))
        print(f"  [FAIL] {label}: {exc!r}")


def eq(a, b, what=""):
    if a != b:
        raise AssertionError(f"{what or 'value'}: expected {b!r}, got {a!r}")


def _base():
    return {
        "state_machines": {
            "SM_A": {"initial": "idle", "states": {"idle": {}, "run": {}}},
        },
        "petri_nets": {"PN_1": {"places": ["p0"]}},
    }


# ======================================================================
def test_backward_compat():
    # 没有 patches 段：load_config 原样返回（无深拷贝负担、无剥离副作用）
    base = _base()
    out = cfg_mod.apply_config_patches(base, None)
    eq(out, base, "无 patch 时结果 == 基底")
    # 不可变：apply 不应改基底
    cfg_mod.apply_config_patches(base, [{"section": "state_machines",
                                        "name": "SM_A",
                                        "override": {"initial": "run"}}])
    eq(base["state_machines"]["SM_A"]["initial"], "idle", "基底未被修改")


def test_override_whole_key():
    base = _base()
    out = cfg_mod.apply_config_patches(base, [
        {"section": "state_machines", "name": "SM_A",
         "override": {"initial": "run"}},
    ])
    eq(out["state_machines"]["SM_A"]["initial"], "run", "override 生效")
    # 整键替换：只替换声明的键，其它键保留
    eq(out["state_machines"]["SM_A"]["states"], {"idle": {}, "run": {}},
       "未声明的键保留")


def test_insert():
    base = _base()
    out = cfg_mod.apply_config_patches(base, [
        {"insert": {"section": "state_machines", "name": "SM_B",
                    "spec": {"initial": "x", "states": {"x": {}}}}},
    ])
    eq(out["state_machines"]["SM_B"]["initial"], "x", "insert 新增实例生效")
    # 基底未变
    assert "SM_B" not in base["state_machines"], "基底未被修改"


def test_missing_target_warn_only():
    base = _base()
    warns = []

    def warn(m):
        warns.append(m)

    # section 不存在
    out = cfg_mod.apply_config_patches(base, [
        {"section": "no_such_section", "name": "X", "override": {"a": 1}},
    ], warn=warn)
    # name 不存在
    cfg_mod.apply_config_patches(base, [
        {"section": "state_machines", "name": "no_such", "override": {"a": 1}},
    ], warn=warn)
    eq(out, base, "目标缺失时不改动配置")
    assert warns, "缺失目标应产生警告"
    assert any("no_such_section" in w for w in warns), "应点名缺失段"
    assert any("no_such" in w for w in warns), "应点名缺失实例"


def test_patches_meta_stripped():
    # load_config 返回的可用配置不应残留 patches 元数据段
    base = _base()
    base["patches"] = [{"section": "state_machines", "name": "SM_A",
                        "override": {"initial": "run"}}]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(base, fh)
        path = fh.name
    try:
        out = cfg_mod.load_config(path)
        assert "patches" not in out, "patches 元数据段应被剥离"
        eq(out["state_machines"]["SM_A"]["initial"], "run", "文件级 patches 生效")
    finally:
        Path(path).unlink()


def test_load_without_patches_unchanged():
    base = _base()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(base, fh)
        path = fh.name
    try:
        out = cfg_mod.load_config(path)
        eq(out, base, "无 patches 段时 load_config 原样返回")
    finally:
        Path(path).unlink()


def main():
    print("=" * 74)
    print("P3 · 配置分层 patches 验证")
    print("=" * 74)
    check("向后兼容：无 patch 时原样返回且基底不可变", test_backward_compat)
    check("override 整键替换生效", test_override_whole_key)
    check("insert 新增实例生效", test_insert)
    check("目标缺失只警告不崩溃", test_missing_target_warn_only)
    check("patches 元数据段被剥离", test_patches_meta_stripped)
    check("无 patches 段 load_config 原样返回", test_load_without_patches_unchanged)

    print("\n" + "=" * 74)
    print(f"通过 {_PASS} 项，失败 {_FAIL} 项")
    if _FAILURES:
        for label, _exc, tb in _FAILURES:
            print("-" * 74)
            print(f"FAILED: {label}")
            print(tb)
    print("=" * 74)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
