<template>
  <div>
    <h1 class="brand">成员</h1>
    <form @submit.prevent="add">
      <input v-model="name" placeholder="新成员姓名" />
      <button type="submit">添加</button>
    </form>
    <p v-if="err" class="err">{{ err }}</p>
    <ul class="list">
      <li v-for="m in rows" :key="m.id">
        <strong>{{ m.name }}</strong>
        <span class="muted"> · {{ m.active ? '在岗' : '停用' }} · {{ m.data_quality }}</span>

        <div v-if="m.active" class="handover-box">
          <button class="ghost" @click="toggle(m.id)">
            {{ panel === m.id ? '收起离场交接' : '离场交接' }}
          </button>

          <div v-if="panel === m.id" class="week-card">
            <label>
              接收周
              <select v-model.number="form.week_id">
                <option v-for="w in weeks" :key="w.id" :value="w.id">{{ w.label }}</option>
              </select>
            </label>
            <label>
              接收人（在岗且 clean）
              <select v-model.number="form.to_member">
                <option
                  v-for="r in receivers(m)"
                  :key="r.id"
                  :value="r.id"
                >{{ r.name }}</option>
              </select>
            </label>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button class="ghost" :disabled="busy" @click="preview(m)">预览接管格子</button>
              <button :disabled="busy || previewed === null" @click="confirm(m)">
                确认签发交接条
              </button>
            </div>

            <p v-if="previewMsg" class="muted" style="margin-top:8px">{{ previewMsg }}</p>
            <ul v-if="previewCells.length" class="list" style="margin-top:6px">
              <li v-for="cell in previewCells" :key="cell.assignment_id">
                <span class="chip">Day {{ cell.day }}</span>
                <span class="chip coral">{{ cell.task_title }}</span>
                <span class="muted">→ 接收人名下</span>
              </li>
            </ul>
            <p v-if="done" class="muted" style="margin-top:8px">
              交接条已签发（{{ done.cell_count }} 格{{ done.voided_swap_ids.length ? '，并自动作废 ' + done.voided_swap_ids.length + ' 条旧对调' : '' }}），
              现在可以停用该成员。
            </p>
            <button
              v-if="done"
              style="margin-top:8px"
              :disabled="busy"
              @click="deactivate(m)"
            >停用 {{ m.name }}</button>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api, errText } from '../api'

const rows = ref([])
const weeks = ref([])
const name = ref('')
const err = ref('')
const busy = ref(false)
const panel = ref(null)
const form = ref({ week_id: 1, to_member: null })
const previewCells = ref([])
const previewMsg = ref('')
const previewed = ref(null)
const done = ref(null)

function receivers(m) {
  return rows.value.filter(r => r.active && r.data_quality === 'clean' && r.id !== m.id)
}

async function load() {
  rows.value = await api('/members')
  weeks.value = await api('/weeks')
  if (!form.value.week_id && weeks.value.length) form.value.week_id = weeks.value[0].id
  if (!form.value.to_member) {
    const first = rows.value.find(r => r.active && r.data_quality === 'clean')
    if (first) form.value.to_member = first.id
  }
}

function toggle(id) {
  if (panel.value === id) {
    panel.value = null
  } else {
    panel.value = id
    previewCells.value = []
    previewMsg.value = ''
    previewed.value = null
    done.value = null
    err.value = ''
    const m = rows.value.find(r => r.id === id)
    const first = receivers(m)[0]
    if (first) form.value.to_member = first.id
  }
}

async function preview(m) {
  err.value = ''
  previewCells.value = []
  previewMsg.value = ''
  previewed.value = null
  done.value = null
  busy.value = true
  try {
    const p = await api('/handovers/preview', {
      method: 'POST',
      body: JSON.stringify({
        week_id: form.value.week_id,
        from_member: m.id,
        to_member: form.value.to_member,
      }),
    })
    previewCells.value = p.cells
    previewed.value = p
    previewMsg.value = p.count
      ? `预览不改库：以下 ${p.count} 格将改派给接收人`
      : '该成员在本周没有名下格子，将只签发离场记录'
  } catch (e) { err.value = errText(e) }
  finally { busy.value = false }
}

async function confirm(m) {
  err.value = ''
  busy.value = true
  try {
    const r = await api('/handovers/confirm', {
      method: 'POST',
      body: JSON.stringify({
        week_id: form.value.week_id,
        from_member: m.id,
        to_member: form.value.to_member,
      }),
    })
    done.value = r
    previewMsg.value = ''
  } catch (e) { err.value = errText(e) }
  finally { busy.value = false }
}

async function deactivate(m) {
  err.value = ''
  busy.value = true
  try {
    await api(`/members/${m.id}/deactivate`, { method: 'POST', body: '{}' })
    panel.value = null
    await load()
  } catch (e) { err.value = errText(e) }
  finally { busy.value = false }
}

async function add() {
  if (!name.value.trim()) return
  await api('/members', { method: 'POST', body: JSON.stringify({ name: name.value }) })
  name.value = ''; await load()
}

onMounted(load)
</script>
<style scoped>
.handover-box { margin-top: 6px; }
</style>
