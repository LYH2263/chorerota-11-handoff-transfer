export async function api(path, opts = {}) {
  const r = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  })
  if (!r.ok) {
    let detail = r.statusText
    try { const j = await r.json(); detail = j.detail || JSON.stringify(j) } catch {}
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (r.status === 204) return null
  return r.json()
}

const REASONS = {
  handover_required: '停用前必须先签发交接条',
  receiver_inactive: '接收人已停用，不能接活',
  receiver_dirty: '接收人数据为脏，不能接活',
  receiver_is_self: '接收人不能就是交出人自己',
  from_member_inactive: '交出人已停用，无需再交',
  member_not_found: '成员不存在',
  week_not_found: '周不存在',
  no_cells: '该成员在本周没有名下格子，无需移交',
  stale_voided: '看板已被改动，该对调已自动作废',
  same_assignee: '两格当前是同一人，无需对调',
  same_slot: '不能对调同一格',
  slot_missing: '格子不存在',
  not_pending: '该对调已不是待处理状态',
}

export function errText(e) {
  const s = e?.message || String(e)
  if (s.startsWith('voided:')) {
    const why = s.slice('voided:'.length)
    return '该对调已作废（' + (why === 'handover_confirmed' ? '离场交接' : why || '看板变动') + '）'
  }
  if (s.startsWith('cells_remaining:')) {
    return `名下还有 ${s.split(':')[1]} 个格子未移交，不能停用`
  }
  return REASONS[s] || s
}
