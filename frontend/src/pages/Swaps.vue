<template>
  <div>
    <h1 class="brand">对调</h1>
    <p class="muted">先生成周表，再填写两格对调（day + task_id）</p>
    <div class="week-card" style="margin-bottom:12px">
      <label>A day <input type="number" v-model.number="form.a_day" /></label>
      <label>A task_id <input type="number" v-model.number="form.a_task" /></label>
      <label>B day <input type="number" v-model.number="form.b_day" /></label>
      <label>B task_id <input type="number" v-model.number="form.b_task" /></label>
      <button @click="request">申请对调</button>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <ul class="list">
      <li v-for="s in rows" :key="s.id">
        #{{ s.id }} D{{ s.a_day }}/T{{ s.a_task }} ↔ D{{ s.b_day }}/T{{ s.b_task }}
        <span class="chip" :class="chipClass(s.status)">{{ statusLabel(s) }}</span>
        <button v-if="s.status==='pending'" style="margin-left:8px" @click="confirm(s.id)">确认改表</button>
      </li>
    </ul>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api, errText } from '../api'
const rows = ref([])
const err = ref('')
const form = ref({ a_day: 0, a_task: 1, b_day: 1, b_task: 1 })

function chipClass(status) {
  if (status === 'pending') return 'coral'
  if (status === 'voided') return 'void'
  return ''
}
function statusLabel(s) {
  if (s.status === 'voided') {
    const why = s.void_reason === 'handover_confirmed' ? '离场交接作废'
      : s.void_reason === 'stale' ? '看板已变动作废'
      : '已作废'
    return why
  }
  return s.status
}

async function load() {
  err.value = ''
  try { rows.value = await api('/swaps') }
  catch (e) { err.value = errText(e) }
}
async function request() {
  err.value = ''
  try {
    await api('/weeks/1/swaps', { method: 'POST', body: JSON.stringify(form.value) })
    await load()
  } catch (e) { err.value = errText(e) }
}
async function confirm(id) {
  err.value = ''
  try { await api('/swaps/' + id + '/confirm', { method: 'POST', body: '{}' }); await load() }
  catch (e) { await load(); err.value = errText(e) }
}
onMounted(load)
</script>
