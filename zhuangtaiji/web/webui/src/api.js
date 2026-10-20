// 与后端 web/server.py 交互的 REST 客户端。
async function req(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const r = await fetch(path, opts)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.error || `${r.status}`)
  return data
}

export const api = {
  engines: () => req('GET', '/api/engines'),
  list: () => req('GET', '/api/orchestrations'),
  get: (name) => req('GET', `/api/orchestration/${encodeURIComponent(name)}`),
  save: (name, payload) => req('PUT', `/api/orchestration/${encodeURIComponent(name)}`, payload),
  remove: (name) => req('DELETE', `/api/orchestration/${encodeURIComponent(name)}`),
  run: (name) => req('POST', `/api/orchestration/${encodeURIComponent(name)}/run`),
  step: (name, engine, ctx) =>
    req('POST', `/api/orchestration/${encodeURIComponent(name)}/step`, { engine, ctx }),
  reset: (name) => req('POST', `/api/orchestration/${encodeURIComponent(name)}/reset`),
}
