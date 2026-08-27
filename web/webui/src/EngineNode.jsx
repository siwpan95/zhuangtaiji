import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'

// 自定义节点：一个被编排的引擎实例。
// 左右各一个 handle，便于用连线表示「绑定」（when -> then）。
function EngineNode({ data, selected }) {
  const summary = (data.summary || '').split('\n').slice(0, 2).join('\n')
  return (
    <div className={`engine-node ${selected ? 'active' : ''}`}>
      <Handle type="target" position={Position.Left} style={{ background: '#8b949e' }} />
      <div className="nk">{data.kind}</div>
      <div className="nm">{data.name}</div>
      <div className="id">@{data.alias}</div>
      <div className="sum">{summary || '—'}</div>
      <Handle type="source" position={Position.Right} style={{ background: '#58a6ff' }} />
    </div>
  )
}

export default memo(EngineNode)
