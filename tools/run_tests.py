# -*- coding: utf-8 -*-
"""项目测试与门禁的统一入口。

用法::

    python tools/run_tests.py            # 跑全部测试
    python tools/run_tests.py --list     # 只列出会被执行的测试
    python tools/run_tests.py ui_verify  # 只跑名字含该子串的测试
    python tools/run_tests.py --verbose  # 打印每个测试的完整输出

**为什么需要这个入口**：改造前，项目里的测试有三重障碍——

1. ``README.md`` 写的命令是 ``python test_verify.py``，但文件实际在 ``test/`` 下；
2. 从 ``test/`` 目录运行会让 ``core`` 不在导入路径，直接 ``ModuleNotFoundError``；
3. 缺 tkinter 的环境下，仅仅 import 一个 GUI 模块就会让**纯逻辑测试**整体崩掉。

本入口统一解决前两条（自动设置 ``PYTHONPATH`` 为项目根、统一工作目录），
并对第三条给出明确分类：**环境缺依赖**记为 ``ENV-SKIP`` 而不是 ``FAIL``——
因为那不是代码缺陷。判定规则：

* 退出码 0 → ``PASS``
* 因 ``ModuleNotFoundError`` 缺**第三方/可选**模块 → ``ENV-SKIP``（附缺失模块名）
* 因 ``ModuleNotFoundError`` 缺**本项目**模块 → ``FAIL``（说明是接线错误）
* 其它非零退出 → ``FAIL``

退出码：有 ``FAIL`` 时为 1，否则为 0（``ENV-SKIP`` 不算失败，避免"环境不同就红"。
但会在汇总里显著提示，防止把环境问题误当通过）。
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, NamedTuple, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = PROJECT_ROOT / "test"

# 本项目自己的顶层包：缺这些说明是接线错误，不是环境问题
PROJECT_PACKAGES = {"core", "engine", "ui", "web", "tools", "test"}

_MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")

#: 测试用这行声明"我需要某个可选模块"（如 ``SKIP-REQUIRES: tkinter``），
#: 门禁据此自动换用带该模块的解释器重试，而不是永久判为环境跳过。
_SKIP_REQUIRES = re.compile(r"SKIP-REQUIRES:\s*([\w.]+)")

#: UI 冒烟测试在 Tk 9 下进程退出阶段会卡死，自身用看门狗以 SIGTERM 硬杀
#: （见 ``test/test_ui_smoke.py`` 顶部 docstring）。因此它即便全部断言通过，
#: 退出码也是 SIGTERM。门禁据此标记识别"完成但被杀"的真实结果。
_TEARDOWN_KILL = re.compile(r"\[teardown\] 测试已完成")
#: 测试结果汇总行，用于从输出中解析失败数（"通过 N 项，失败 M 项"）。
_FAIL_COUNT = re.compile(r"失败\s*(\d+)\s*项")

PASS = "PASS"
FAIL = "FAIL"
ENV_SKIP = "ENV-SKIP"
TIMEOUT = "TIMEOUT"

#: 单个测试的运行上限（秒）。超时即判失败——**门禁不能无限挂起**：
#: 一个卡住的测试会让整条流水线无声无息地停在这里，比"明确的失败"糟糕得多。
DEFAULT_TEST_TIMEOUT = 180

#: 测试自行声明"前置条件未就绪"时使用的退出码（沿用 autotools 约定）。
#: 与"失败"区分开，避免把环境问题误报为代码缺陷。
SKIP_EXIT_CODE = 77

#: 需要"更合适的解释器"才能跑的模块 → 哪些解释器特性可以解它。
#: 键是缺失的模块名，值是用于挑选解释器的探测表达式。
_INTERPRETER_FEATURES = {
    "tkinter": "import tkinter",
}

_tk_interpreters: Optional[List[str]] = None

#: ``--python`` 指定的首选解释器（默认是当前正在运行本脚本的解释器）。
_preferred_interpreter: Optional[str] = None


class Result(NamedTuple):
    name: str
    status: str
    detail: str
    seconds: float
    output: str


def discover() -> List[Path]:
    """按文件名排序返回 ``test/test_*.py``。"""
    if not TEST_DIR.is_dir():
        return []
    return sorted(p for p in TEST_DIR.glob("test_*.py") if p.is_file())


def _candidate_interpreters() -> List[str]:
    """汇总本机可能的 Python 解释器路径（含 C/D/E… 等各盘符的常见安装位置）。

    只考虑常见安装根，不做全盘扫描——那会慢到不可用。
    """
    exe_name = "python.exe" if os.name == "nt" else "python3"
    cands: List[str] = [sys.executable]
    for name in ("python", "python3", "pythonw"):
        found = shutil.which(name)
        if found:
            cands.append(found)

    patterns: List[str] = []
    for drive in ("C", "D", "E", "F", "G"):
        patterns += [f"{drive}:/Python*", f"{drive}:/python*",
                     f"{drive}:/Program Files/Python*"]
    for var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(var)
        if base:
            patterns.append(str(Path(base) / "Programs" / "Python" / "Python*"))
            patterns.append(str(Path(base) / "Python*"))
    for pattern in patterns:
        for directory in sorted(glob.glob(pattern), reverse=True):
            path = Path(directory) / exe_name
            if path.exists():
                cands.append(str(path))

    unique: List[str] = []
    seen = set()
    for c in cands:
        try:
            key = os.path.normcase(os.path.abspath(c))
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def interpreters_with(module: str, timeout: int = 25) -> List[str]:
    """返回本机能成功 ``import <module>`` 的解释器列表（结果会缓存）。

    :param module: 要探测的模块名，如 ``"tkinter"``。
    :param timeout: 单个解释器的探测超时（秒）。
    :returns: 可用的解释器绝对路径，按候选顺序。
    """
    global _tk_interpreters
    if module == "tkinter" and _tk_interpreters is not None:
        return _tk_interpreters

    probe = _INTERPRETER_FEATURES.get(module, f"import {module}")
    found: List[str] = []
    for exe in _candidate_interpreters():
        try:
            proc = subprocess.run([exe, "-c", probe], capture_output=True,
                                  timeout=timeout)
        except Exception:
            continue
        if proc.returncode == 0 and exe != sys.executable:
            found.append(exe)
    if module == "tkinter":
        _tk_interpreters = found
    return found


def _classify(returncode: int, stderr: str) -> tuple[str, str]:
    """把一次运行结果归类为 PASS / ENV-SKIP / FAIL。

    :param returncode: 子进程退出码。
    :param stderr: 子进程标准错误。
    :returns: ``(状态, 说明)``。
    """
    if returncode == 0:
        return PASS, ""

    if returncode == SKIP_EXIT_CODE:
        return ENV_SKIP, "测试自行声明前置条件未就绪（详见输出）"

    match = _MISSING_MODULE.search(stderr)
    if match:
        module = match.group(1).split(".")[0]
        if module not in PROJECT_PACKAGES:
            return ENV_SKIP, f"缺少可选依赖 {module!r}（环境问题，非代码缺陷）"
        return FAIL, f"缺少本项目模块 {module!r}（导入路径接线错误）"

    return FAIL, f"退出码 {returncode}"


def _teardown_kill_status(proc) -> Optional[tuple[str, str]]:
    """UI 冒烟测试在 Tk 9 下退出阶段卡死、由自身看门狗 SIGTERM 硬杀。

    它即便全部断言通过，退出码也是 SIGTERM（非 0）。这里依据其打印的完成汇总
    判定真实结果，避免把"被看门狗杀掉"误判为失败。

    :param proc: 子进程结果（可能 ``None``，表示超时未捕获）。
    :returns: ``(状态, 说明)``，或 ``None``（不属于该情形）。
    """
    if proc is None:
        return None
    out = proc.stdout or ""
    if not _TEARDOWN_KILL.search(out):
        return None
    m = _FAIL_COUNT.search(out)
    if m is None:
        return None
    failed = int(m.group(1))
    if failed == 0:
        return PASS, "全部断言通过；退出码为看门狗硬杀（Tk9 收尾卡死，非代码缺陷）"
    return FAIL, f"看门狗硬杀前已有 {failed} 项失败"


def _run(path: Path, interpreter: str,
         timeout: int = DEFAULT_TEST_TIMEOUT) -> tuple[Optional[subprocess.CompletedProcess], bool]:
    """用指定解释器在项目根目录下运行测试。

    :param path: 测试文件。
    :param interpreter: 解释器路径。
    :param timeout: 超时秒数。
    :returns: ``(进程结果, 是否超时)``；超时时进程结果为 ``None``。
    """
    env = dict(os.environ)
    # 让 test/ 下的脚本能 import core / engine / ui / web
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + existing if existing else "")
    env["PYTHONIOENCODING"] = "utf-8"      # 避免 Windows 控制台编码把输出打死
    try:
        proc = subprocess.run(
            [interpreter, str(path)],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        print(partial, end="", flush=True)      # 保留已产生的输出，便于定位卡点
        return None, True
    return proc, False


def run_one(path: Path, verbose: bool,
            timeout: int = DEFAULT_TEST_TIMEOUT) -> Result:
    """运行单个测试；必要时自动换用具备所需依赖的解释器。

    若默认解释器因缺少可选模块（如 ``tkinter``）而无法运行，且本机存在带该
    模块的解释器，则自动重试——这样"UI 测试"不会仅仅因为默认解释器不完整
    就永远停在 ENV-SKIP，同时也不影响其它解释器环境的行为。
    """
    primary = _preferred_interpreter or sys.executable
    started = time.perf_counter()
    proc, timed_out = _run(path, primary, timeout)
    used = primary

    if timed_out:
        return Result(path.stem, TIMEOUT,
                      f"超过 {timeout}s 未结束（解释器 {used}）",
                      time.perf_counter() - started, "")

    status, detail = _classify(proc.returncode, proc.stderr or "")

    # UI 冒烟测试：即便全部通过，退出码也是 SIGTERM（看门狗硬杀 Tk9 卡死）。
    # 依据其打印的完成汇总判定真实结果，而不是把"被杀"当失败。
    _tb = _teardown_kill_status(proc)
    if _tb is not None:
        status, detail = _tb

    if status == ENV_SKIP:
        # 两种线索：(a) 未捕获的 ModuleNotFoundError；(b) 测试用 SKIP-REQUIRES
        # 主动声明所需模块。两者都指向"换个解释器可能就跑得起来"。
        combined = (proc.stdout or "") + (proc.stderr or "")
        match = _MISSING_MODULE.search(combined) or _SKIP_REQUIRES.search(combined)
        module = match.group(1).split(".")[0] if match else None
        if module:
            for alt in interpreters_with(module):
                alt_proc, alt_timeout = _run(path, alt, timeout)
                if alt_timeout:
                    return Result(path.stem, TIMEOUT,
                                  f"备用解释器 {alt} 超过 {timeout}s 未结束",
                                  time.perf_counter() - started, "")
                alt_status, alt_detail = _classify(alt_proc.returncode,
                                                   alt_proc.stderr or "")
                alt_tb = _teardown_kill_status(alt_proc)
                if alt_tb is not None:
                    alt_status, alt_detail = alt_tb
                if alt_status != ENV_SKIP:
                    proc, status, detail, used = alt_proc, alt_status, alt_detail, alt
                    break

    elapsed = time.perf_counter() - started
    output = (proc.stdout or "") + (proc.stderr or "")
    if verbose:
        print(f"\n--- {path.name} (interpreter={used}) ---")
        print(output)
    note = detail
    if used != primary and status == PASS:
        note = (f"{detail}；" if detail else "") + f"使用了备用解释器 {Path(used).name}"
    return Result(path.stem, status, note, elapsed, output)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="运行 zhuangtaiji 的全部测试（统一 PYTHONPATH 与结果分类）")
    parser.add_argument("filter", nargs="*", default=[],
                        help="只跑名字包含这些子串的测试")
    parser.add_argument("--list", action="store_true", help="只列出会被执行的测试")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="打印每个测试的完整输出")
    parser.add_argument("--python", metavar="PATH", default=None,
                        help="指定首选解释器（默认用当前解释器；"
                             "缺 tkinter 等可选模块时会自动换用备用解释器）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TEST_TIMEOUT,
                        metavar="SEC", help=f"单个测试的超时秒数"
                                            f"（默认 {DEFAULT_TEST_TIMEOUT}）")
    args = parser.parse_args(argv)

    global _preferred_interpreter
    if args.python:
        if not Path(args.python).exists():
            print(f"指定的解释器不存在：{args.python}")
            return 2
        _preferred_interpreter = args.python

    tests = discover()
    if args.filter:
        tests = [t for t in tests if any(f in t.stem for f in args.filter)]

    if not tests:
        print(f"未找到测试（目录：{TEST_DIR}）")
        return 1

    if args.list:
        for t in tests:
            print(f"  {t.relative_to(PROJECT_ROOT)}")
        return 0

    print("=" * 78)
    print(f"zhuangtaiji 测试门禁 · 共 {len(tests)} 项 · 根目录 {PROJECT_ROOT}")
    print("=" * 78)

    results: List[Result] = []
    for t in tests:
        result = run_one(t, args.verbose, args.timeout)
        results.append(result)
        mark = {PASS: "  ok  ", FAIL: " FAIL ", ENV_SKIP: " skip ",
                TIMEOUT: " T/O  "}[result.status]
        suffix = f" · {result.detail}" if result.detail else ""
        print(f"[{mark}] {result.name:<24} {result.seconds:6.2f}s{suffix}")

    passed = [r for r in results if r.status == PASS]
    failed = [r for r in results if r.status in (FAIL, TIMEOUT)]
    skipped = [r for r in results if r.status == ENV_SKIP]
    timed_out = [r for r in results if r.status == TIMEOUT]

    print("-" * 78)
    print(f"通过 {len(passed)} · 失败 {len(failed)} · 环境跳过 {len(skipped)}")
    if timed_out:
        print(f"（其中 {len(timed_out)} 项为超时："
              f"{[r.name for r in timed_out]}；可用 --timeout 调整上限）")

    if skipped:
        print("\n环境跳过（不计为失败，但请确认这是预期的）：")
        for r in skipped:
            print(f"  · {r.name}: {r.detail}")

    if failed:
        print("\n失败详情：")
        for r in failed:
            print(f"\n### {r.name}: {r.detail}")
            tail = "\n".join(r.output.strip().splitlines()[-25:])
            print(tail)

    print("=" * 78)
    if failed:
        print("结果：失败")
        return 1
    print("结果：通过" + ("（含环境跳过项）" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
