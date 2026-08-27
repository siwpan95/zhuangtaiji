# -*- coding: utf-8 -*-
"""
互操作适配器（P1-2）
===================

让工作台与专业工具互通，并支持运行轨迹审计导出：

* ``petri_to_pnml`` / ``petri_from_pnml`` —— Petri 网 ⇄ PNML（标准交换格式）。
* ``fsm_to_scxml`` / ``fsm_from_scxml`` —— 状态机 ⇄ SCXML（W3C 状态机标准）。
* ``fsm_to_xstate`` / ``xstate_to_fsm`` —— 状态机 ⇄ XState JSON（Stately.ai）。
* ``graph_to_dot`` / ``graph_to_mermaid`` —— 复用 renderers 导出图。
* ``export_trace_csv`` / ``export_trace_json`` —— 运行轨迹审计。

全部基于标准库（xml.etree / json），无外部依赖。
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from . import renderers
from .engine_base import Graph


# ==========================================================
# Petri 网 ⇄ PNML
# ==========================================================
def petri_to_pnml(pn) -> str:
    root = ET.Element("pnml")
    net = ET.SubElement(root, "net", id="net1",
                        type="pnmlcoremodel")
    page = ET.SubElement(net, "page", id="page1")
    for p, tok in pn.places.items():
        place = ET.SubElement(page, "place", id=f"P_{p}")
        im = ET.SubElement(place, "initialMarking")
        ET.SubElement(im, "text").text = str(tok)
    for t in pn.transitions:
        ET.SubElement(page, "transition", id=f"T_{t}")
    arc_id = 0

    def add_arc(src, dst, w, kind="normal"):
        nonlocal arc_id
        arc_id += 1
        a = ET.SubElement(page, "arc", id=f"a{arc_id}",
                          source=src, target=dst)
        if kind == "inhibitor":
            a.set("type", "inhibitor")
        if w != 1:
            ins = ET.SubElement(a, "inscription")
            ET.SubElement(ins, "text").text = str(w)

    for tname, t in pn.transitions.items():
        for p, w in t.inputs:
            add_arc(f"P_{p}", f"T_{tname}", w)
        for p, w in t.outputs:
            add_arc(f"T_{tname}", f"P_{p}", w)
        for p, w in t.inhibitors:
            add_arc(f"P_{p}", f"T_{tname}", w, kind="inhibitor")
    return _prettify(root)


def petri_from_pnml(xml: str) -> Dict[str, Any]:
    root = ET.fromstring(xml)
    places: Dict[str, int] = {}
    transitions: Dict[str, Dict[str, List]] = {}
    for place in root.iter("place"):
        pid = place.get("id").lstrip("P_")
        tok = 0
        im = place.find("initialMarking/text")
        if im is not None and im.text:
            tok = int(im.text)
        places[pid] = tok
    for tr in root.iter("transition"):
        tid = tr.get("id").lstrip("T_")
        transitions[tid] = {"inputs": [], "outputs": [], "inhibitors": []}
    for arc in root.iter("arc"):
        src, dst = arc.get("source"), arc.get("target")
        is_inh = arc.get("type") == "inhibitor"
        w = 1
        ins = arc.find("inscription/text")
        if ins is not None and ins.text:
            try:
                w = int(ins.text)
            except ValueError:
                pass
        sp, dp = src[2:], dst[2:]  # 去掉 "P_"/"T_" 前缀
        if is_inh and src.startswith("P_") and dst.startswith("T_"):
            transitions[dp]["inhibitors"].append([sp, w])
        elif src.startswith("P_") and dst.startswith("T_"):
            transitions[dp]["inputs"].append([sp, w])
        elif src.startswith("T_") and dst.startswith("P_"):
            transitions[sp]["outputs"].append([dp, w])
    return {"name": "imported", "places": places, "transitions": transitions}


# ==========================================================
# 状态机 ⇄ SCXML
# ==========================================================
def fsm_to_scxml(spec: Dict[str, Any]) -> str:
    root = ET.Element("scxml", xmlns="http://www.w3.org/2005/07/scxml",
                      initial=spec.get("initial", ""))
    states = spec.get("states", {})

    def add_state(parent, sid, s):
        st = ET.SubElement(parent, "state", id=sid)
        if s.get("content"):
            ET.SubElement(st, "onentry").text = s["content"]
        for ev, tgt in (s.get("transitions") or {}).items():
            t = tgt.get("target") if isinstance(tgt, dict) else tgt
            ET.SubElement(st, "transition", event=ev,
                          target=t.lstrip("#") if isinstance(t, str) else t)
        if "substates" in s:
            for csid, cs in s["substates"].items():
                add_state(st, csid, cs)

    for sid, s in states.items():
        add_state(root, sid, s)
    return _prettify(root)


def fsm_from_scxml(xml: str) -> Dict[str, Any]:
    root = ET.fromstring(xml)
    # 剥离命名空间（scxml 默认带 xmlns，否则 findall 匹配不到）
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    spec: Dict[str, Any] = {"initial": root.get("initial", ""), "states": {}}

    def parse_state(el):
        sid = el.get("id")
        s: Dict[str, Any] = {}
        entry = el.find("onentry")
        if entry is not None and entry.text:
            s["content"] = entry.text
        transitions = {}
        for tr in el.findall("transition"):
            transitions[tr.get("event")] = tr.get("target")
        if transitions:
            s["transitions"] = transitions
        sub = [c for c in el.findall("state")]
        if sub:
            s["substates"] = {}
            for c in sub:
                s["substates"][c.get("id")] = parse_state(c)
        return s

    for el in root.findall("state"):
        spec["states"][el.get("id")] = parse_state(el)
    return spec


# ==========================================================
# 状态机 ⇄ XState JSON
# ==========================================================
def fsm_to_xstate(spec: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"initial": spec.get("initial", ""),
                           "states": {}}

    def conv(sid, s):
        node: Dict[str, Any] = {}
        if s.get("content"):
            node["meta"] = {"content": s["content"]}
        on = {}
        for ev, tgt in (s.get("transitions") or {}).items():
            t = tgt.get("target") if isinstance(tgt, dict) else tgt
            on[ev] = t.lstrip("#") if isinstance(t, str) else t
        if on:
            node["on"] = on
        if "substates" in s:
            node["initial"] = s.get("initial")
            node["states"] = {}
            for csid, cs in s["substates"].items():
                node["states"][csid] = conv(csid, cs)
        return node

    for sid, s in spec.get("states", {}).items():
        out["states"][sid] = conv(sid, s)
    return out


def xstate_to_fsm(d: Dict[str, Any]) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"initial": d.get("initial", ""), "states": {}}

    def conv(sid, node):
        s: Dict[str, Any] = {}
        if node.get("meta", {}).get("content"):
            s["content"] = node["meta"]["content"]
        on = node.get("on", {})
        if on:
            s["transitions"] = dict(on)
        sub = node.get("states")
        if sub:
            s["initial"] = node.get("initial")
            s["substates"] = {}
            for csid, cs in sub.items():
                s["substates"][csid] = conv(csid, cs)
        return s

    for sid, node in d.get("states", {}).items():
        spec["states"][sid] = conv(sid, node)
    return spec


# ==========================================================
# 图导出（复用 renderers）
# ==========================================================
def graph_to_dot(g: Graph) -> str:
    return renderers.to_dot(g)


def graph_to_mermaid(g: Graph) -> str:
    return renderers.to_mermaid(g)


# ==========================================================
# 轨迹审计导出
# ==========================================================
def export_trace_csv(trace: List[Dict[str, Any]]) -> str:
    if not trace:
        return ""
    cols: List[str] = []
    for row in trace:
        for k in row:
            if k not in cols:
                cols.append(k)
    lines = [",".join(cols)]
    for row in trace:
        lines.append(",".join(str(row.get(c, "")) for c in cols))
    return "\n".join(lines)


def export_trace_json(trace: List[Dict[str, Any]]) -> str:
    return json.dumps(trace, ensure_ascii=False, indent=2)


# ==========================================================
# 工具
# ==========================================================
def _prettify(elem: ET.Element) -> str:
    try:
        from xml.dom import minidom
        return minidom.parseString(
            ET.tostring(elem, encoding="unicode")).toprettyxml(indent="  ")
    except Exception:
        return ET.tostring(elem, encoding="unicode")
