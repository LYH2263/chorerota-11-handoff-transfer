<template>
  <div>
    <h1 class="brand">本周看板</h1>
    <p class="muted">周卡片网格 · round-robin 落位后可去「对调」申请交换</p>
    <div style="display:flex;gap:8px;margin:12px 0">
      <button @click="generate">生成周表</button>
      <button class="ghost" @click="load">刷新</button>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="week-grid">
      <article v-for="d in days" :key="d" class="week-card">
        <header>Day {{ d }}</header>
        <div v-for="a in byDay(d)" :key="a.id">
          <span class="chip">{{ a.task_title }}</span>
          <span class="chip coral">{{ a.member_name }}</span>
        </div>
        <p v-if="!byDay(d).length" class="muted">空</p>
      </article>
    </div>

    <section v-if="handovers.length" style="margin-top:20px">
      <h2 class="brand" style="font-size:16px">移交清单</h2>
      <p class="muted">本周已确认的离场交接条，与看板同钉</p>
      <article v-for="h in handovers" :key="h.id" class="week-card handover-card">
        <header>
          <strong>{{ h.from_member_name }}</strong>
          <span class="muted"> 离场 · 交棒 </span>
          <strong>{{ h.to_member_name }}</strong>
          <span class="chip" style="margin-left:6px">{{ h.cell_count }} 格</span>
        </header>
        <div v-for="cell in h.cells" :key="cell.day + '-' + cell.task_id">
          <span class="chip">Day {{ cell.day }}</span>
          <span class="chip coral">{{ cell.task_title }}</span>
        </div>
        <p v-if="h.note" class="muted" style="margin-top:6px">备注：{{ h.note }}</p>
      </article>
    </section>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const assigns = ref([])
const handovers = ref([])
const days = [0,1,2,3,4,5,6]
const err = ref('')
const weekId = 1
function byDay(d) { return assigns.value.filter(a => a.day === d) }
async function load() {
  err.value = ''
  try {
    const b = await api('/weeks/' + weekId + '/board')
    assigns.value = b.assignments || []
    handovers.value = b.handovers || []
  } catch (e) { err.value = e.message }
}
async function generate() {
  err.value = ''
  try { await api('/weeks/' + weekId + '/generate', { method: 'POST', body: '{}' }); await load() }
  catch (e) { err.value = e.message }
}
onMounted(load)
</script>
