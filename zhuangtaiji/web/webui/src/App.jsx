import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap, Panel,
  ReactFlowProvider, applyNodeChanges, applyEdgeChanges, addEdge,
  useReactFlow,
} from '@xyflow/react'
import EngineNode from './EngineNode.jsx'
import { api } from './api.js'

const EVENT_TYPES = ['*', 'enter', 'tick', 'fired', 'step', 'decide', 'change']

const KIND_COLOR = {
  state_machine: '#58a6ff',
  behavior_tree: '#3fb950',
  decision_tree: '#e3b341',
  petri_net: '#f778ba',
  markov_chain: '#a371f7',
  rule_engine: '#ff7b72',
  difference_engine: '#39c5cf',
}

let seq = 1
const newId = () => `node_${seq++}`
const edgeLabel = (d) => `${d?.etype || '*'} → ${d?.action || 'step'}`

function Editor() {
  const rf = useReactFlow()
  const [catalog, setCatalog] = useState({})
  const [orchList, setOrchList] = useState([])
  const [current, setCurrent] = useState('')
  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])
  const [description, setDescription] = useState('')
  const [selected, setSelected] = useState(null) // {type:'node'|'edge', id}
  const [trace, setTrace] = useState([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const nodeTypes = useMemo(() => ({ engine: EngineNode }), [])

  const flash = (m) => { setMsg(m); setTimeout(() => setMsg(''), 2500) }

  // ---- 初始化：拉取目录 + 编排列表，加载第一个 ----
  useEffect(() => {
    ;(async () => {
      try {
        const eng = await api.engines()
        setCatalog(eng)
        const list = await api.list()
        setOrchList(list.list || [])
        if ((list.list || []).length) loadOrch(list.list[0].name)
      } catch (e) { flash('初始化失败: ' + e.message) }
    })()
  }, [])

  const mergeStatus = useCallback((graph) => {
    const gnodes = (graph?.nodes || [])
    const gedges = (graph?.edges || [])
    setNodes((nds) => nds.map((n) => {
      const g = gnodes.find((x) => x.id === n.id)
      return g ? { ...n, data: { ...n.data, summary: g.data?.summary || '' } } : n
    }))
    setEdges((es) => es.map((e) => {
      const g = gedges.find((x) => x.id === e.id)
      return g ? { ...e, label: g.label } : e
    }))
    setTrace(graph?.trace || [])
  }, [])

  const loadOrch = useCallback(async (name) => {
    try {
      const g = await api.get(name)
      const ns = (g.nodes || []).map((n) => ({
        id: n.id,
        type: 'engine',
        position: n.position || { x: 40, y: 40 },
        data: { ...n.data, alias: n.id, summary: n.data?.summary || '' },
      }))
      const es = (g.edges || []).map((e) => ({
        id: e.id, source: e.source, target: e.target,
        label: e.label, data: e.data || { etype: '*', action: 'step', ctx: {} },
      }))
      setCurrent(name)
      setDescription(g.description || '')
      setNodes(ns)
      setEdges(es)
      setSelected(null)
      setTrace(g.trace || [])
    } catch (e) { flash('加载失败: ' + e.message) }
  }, [])

  // ---- 画布交互 ----
  const onNodesChange = useCallback((c) => setNodes((nds) => applyNodeChanges(c, nds)), [])
  const onEdgesChange = useCallback((c) => setEdges((es) => applyEdgeChanges(c, es)), [])
  const onConnect = useCallback((c) => {
    setEdges((es) => addEdge({
      ...c,
      data: { etype: '*', action: 'step', ctx: {} },
      label: edgeLabel({ etype: '*', action: 'step' }),
    }, es))
  }, [])

  const onDrop = useCallback((ev) => {
    ev.preventDefault()
    const raw = ev.dataTransfer.getData('application/reactflow')
    if (!raw) return
    let item
    try { item = JSON.parse(raw) } catch { return }
    const pos = rf.screenToFlowPosition({ x: ev.clientX, y: ev.clientY })
    const id = newId()
    setNodes((nds) => nds.concat({
      id, type: 'engine', position: pos,
      data: { kind: item.kind, name: item.name, alias: id, summary: '' },
    }))
  }, [rf])

  const onDragOver = useCallback((ev) => {
    ev.preventDefault()
    ev.dataTransfer.dropEffect = 'move'
  }, [])

  const onNodeClick = (_, n) => setSelected({ type: 'node', id: n.id })
  const onEdgeClick = (_, e) => setSelected({ type: 'edge', id: e.id })
  const onPaneClick = () => setSelected(null)

  // ---- 工具栏动作 ----
  const save = useCallback(async () => {
    if (!current) return flash('未选择编排')
    setBusy(true)
    try {
      await api.save(current, { description, nodes, edges, start: [] })
      flash('已保存: ' + current)
      const list = await api.list()
      setOrchList(list.list || [])
    } catch (e) { flash('保存失败: ' + e.message) }
    finally { setBusy(false) }
  }, [current, description, nodes, edges])

  const newOrch = useCallback(async () => {
    const name = window.prompt('新编排名称（英文/数字）:')
    if (!name) return
    setBusy(true)
    try {
      await api.save(name, { description: '', nodes: [], edges: [], start: [] })
      const list = await api.list()
      setOrchList(list.list || [])
      await loadOrch(name)
      flash('已创建: ' + name)
    } catch (e) { flash('创建失败: ' + e.message) }
    finally { setBusy(false) }
  }, [loadOrch])

  const deleteOrch = useCallback(async () => {
    if (!current) return
    if (!window.confirm(`删除编排 "${current}" ?`)) return
    setBusy(true)
    try {
      await api.remove(current)
      const list = await api.list()
      setOrchList(list.list || [])
      if (list.list.length) loadOrch(list.list[0].name)
      else { setCurrent(''); setNodes([]); setEdges([]); setDescription('') }
    } catch (e) { flash(e.message) }
    finally { setBusy(false) }
  }, [current, loadOrch])

  const run = useCallback(async () => {
    if (!current) return
    setBusy(true)
    try {
      const r = await api.run(current)
      mergeStatus(r.graph)
      flash('已运行')
    } catch (e) { flash('运行失败: ' + e.message) }
    finally { setBusy(false) }
  }, [current, mergeStatus])

  const reset = useCallback(async () => {
    if (!current) return
    setBusy(true)
    try {
      const r = await api.reset(current)
      mergeStatus(r.graph)
      flash('已重置')
    } catch (e) { flash('重置失败: ' + e.message) }
    finally { setBusy(false) }
  }, [current, mergeStatus])

  const stepNode = useCallback(async (alias, ctxText) => {
    if (!current) return
    let ctx = {}
    try { ctx = ctxText ? JSON.parse(ctxText) : {} } catch { return flash('ctx 不是合法 JSON') }
    setBusy(true)
    try {
      const r = await api.step(current, alias, ctx)
      mergeStatus(r.graph)
      flash(`已驱动 ${alias} -> ${r.result}`)
    } catch (e) { flash('驱动失败: ' + e.message) }
    finally { setBusy(false) }
  }, [current, mergeStatus])

  const deleteSelected = useCallback(() => {
    if (!selected) return
    if (selected.type === 'node') setNodes((nds) => nds.filter((n) => n.id !== selected.id))
    else setEdges((es) => es.filter((e) => e.id !== selected.id))
    setSelected(null)
  }, [selected])

  // ---- 编辑选中节点/边 ----
  const selNode = selected?.type === 'node' ? nodes.find((n) => n.id === selected.id) : null
  const selEdge = selected?.type === 'edge' ? edges.find((e) => e.id === selected.id) : null

  const updateNodeData = (patch) => setNodes((nds) =>
    nds.map((n) => n.id === selNode.id ? { ...n, data: { ...n.data, ...patch } } : n))
  const updateEdgeData = (patch) => setEdges((es) =>
    es.map((e) => e.id === selEdge.id
      ? { ...e, data: { ...e.data, ...patch }, label: edgeLabel({ ...e.data, ...patch }) }
      : e))

  const ctxDefault = selNode?.data.kind === 'state_machine' ? '{"event":"start"}' : '{}'

  return (
    <div className="app">
      <div className="toolbar">
        <h1>🧩 编排编辑器</h1>
        <select value={current} onChange={(e) => loadOrch(e.target.value)} disabled={busy}>
          {orchList.map((o) => (
            <option key={o.name} value={o.name}>
              {o.name} {o.source === 'user' ? '★' : ''}
            </option>
          ))}
        </select>
        <button onClick={newOrch} disabled={busy}>＋ 新建</button>
        <button className="primary" onClick={save} disabled={busy}>💾 保存</button>
        <button onClick={deleteOrch} className="danger" disabled={busy}>🗑 删除</button>
        <button className="primary" onClick={run} disabled={busy}>▶ 运行</button>
        <button onClick={reset} disabled={busy}>🔄 重置</button>
        <input className="desc" placeholder="编排描述…" value={description}
               onChange={(e) => setDescription(e.target.value)} />
        {msg && <span style={{ color: 'var(--green)', fontSize: 12 }}>{msg}</span>}
      </div>

      <div className="body">
        <div className="palette">
          <h3>可用引擎（拖到画布）</h3>
          <div className="hint">从右侧 handle 拖出连线即建立「绑定」：左引擎的某事件 → 右引擎的某动作。</div>
          {Object.entries(catalog).map(([kind, names]) => (
            <div className="group" key={kind}>
              <div className="kind" style={{ color: KIND_COLOR[kind] || 'var(--accent)' }}>{kind}</div>
              {(names || []).map((nm) => (
                <div key={nm} className="item" draggable
                     onDragStart={(e) => e.dataTransfer.setData('application/reactflow',
                       JSON.stringify({ kind, name: nm }))}>
                  {nm}
                </div>
              ))}
            </div>
          ))}
        </div>

        <div className="canvas-wrap" onDrop={onDrop} onDragOver={onDragOver}>
          <div className="reactflow-wrap">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onEdgeClick={onEdgeClick}
              onPaneClick={onPaneClick}
              fitView
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#30363d" gap={18} />
              <Controls />
              <MiniMap pannable zoomable
                       nodeColor={(n) => KIND_COLOR[n.data?.kind] || '#888'}
                       maskColor="rgba(13,17,23,.6)" />
              <Panel position="top-right" style={{ color: 'var(--muted)', fontSize: 11 }}>
                节点 {nodes.length} · 绑定 {edges.length}
              </Panel>
            </ReactFlow>
          </div>
        </div>

        <div className="inspector">
          {selNode && (
            <div>
              <h3>节点 · {selNode.data.alias}</h3>
              <label>范式 kind</label>
              <input value={selNode.data.kind} readOnly />
              <label>实例 name</label>
              <input value={selNode.data.name} readOnly />
              <label>驱动 ctx (JSON)</label>
              <textarea id="ctx" rows={2} defaultValue={ctxDefault} />
              <div className="row" style={{ marginTop: 6 }}>
                <button className="go" onClick={() =>
                  stepNode(selNode.data.alias, document.getElementById('ctx').value)}>
                  ▶ 单步驱动
                </button>
                <button className="danger" onClick={deleteSelected}>删除节点</button>
              </div>
              <label>实时摘要</label>
              <pre>{selNode.data.summary || '—'}</pre>
            </div>
          )}

          {selEdge && (
            <div>
              <h3>绑定 · {selEdge.source} → {selEdge.target}</h3>
              <label>触发事件 etype</label>
              <select value={selEdge.data?.etype || '*'}
                      onChange={(e) => updateEdgeData({ etype: e.target.value })}>
                {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <label>目标动作 action</label>
              <input value={selEdge.data?.action || 'step'}
                     onChange={(e) => updateEdgeData({ action: e.target.value })} />
              <label>附加 ctx (JSON)</label>
              <textarea rows={2} defaultValue={JSON.stringify(selEdge.data?.ctx || {})}
                        onBlur={(e) => { try { updateEdgeData({ ctx: JSON.parse(e.target.value || '{}') }) } catch {} }} />
              <div className="row" style={{ marginTop: 6 }}>
                <button className="danger" onClick={deleteSelected}>删除绑定</button>
              </div>
            </div>
          )}

          {!selNode && !selEdge && (
            <div className="hint" style={{ color: 'var(--muted)' }}>
              点击节点可单步驱动该引擎；点击连线可编辑「触发事件 / 目标动作」。拖动画布空白处取消选择。
            </div>
          )}

          <div>
            <h3>引擎状态</h3>
            <div className="status-list">
              {nodes.map((n) => (
                <div className="s" key={n.id}>
                  <b>{n.data.alias}</b> <span style={{ color: 'var(--muted)' }}>· {n.data.name}</span>
                  <div className="sum">{n.data.summary || '—'}</div>
                </div>
              ))}
              {!nodes.length && <div className="hint">暂无引擎</div>}
            </div>
          </div>

          <div>
            <h3>执行轨迹</h3>
            <div className="trace">
              {trace.length === 0 && <span className="ev">（运行后显示）</span>}
              {trace.map((t, i) => (
                <div key={i}>
                  {t.event
                    ? <span className="ev">• 事件 {t.event} {JSON.stringify(t.payload)}</span>
                    : <span className="act">→ {t.trigger} ⇒ {t.action} = {JSON.stringify(t.result)}</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <Editor />
    </ReactFlowProvider>
  )
}
