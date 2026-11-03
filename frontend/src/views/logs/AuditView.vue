<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElAlert, ElButton, ElDialog, ElEmpty, ElTag } from 'element-plus'
import { request } from '../../api/client'
import type { Page } from '../../types/api'
import type { FieldChange } from '../../types/base-data'
import { displayValue, errorMessage } from '../../utils/base-data'
import ChangeTable from '../../components/ChangeTable.vue'
import PageNav from '../../components/PageNav.vue'

interface Audit {
  id: string
  business_operation_id: string | null
  actor_name_snapshot: string
  entry_source: string
  action_code: string
  target_type: string
  target_id: string | null
  target_label_snapshot: string
  outcome: 'SUCCEEDED' | 'FAILED'
  reason: string | null
  created_at: string
  changes_json?: { before: unknown; after: unknown; changes?: FieldChange[]; errors?: unknown[]; affected_dates?: string[] }
}

const rows = ref<Audit[]>([])
const total = ref('0')
const loading = ref(false)
const error = ref('')
const opened = ref(false)
const selected = ref<Audit | null>(null)
const query = reactive({ q: '', outcome: '', target_type: '', start_date: '', end_date: '', page: 1, page_size: 20 })
let sequence = 0

async function load() {
  const current = ++sequence
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams()
    for (const [field, value] of Object.entries(query)) if (value !== '') params.set(field, String(value))
    const response = await request<Page<Audit>>(`/audit-logs?${params}`)
    if (current !== sequence) return
    rows.value = response.data?.items ?? []
    total.value = response.data?.total ?? '0'
  } catch (cause) { if (current === sequence) error.value = errorMessage(cause) }
  finally { if (current === sequence) loading.value = false }
}

async function details(row: Audit) {
  loading.value = true
  error.value = ''
  try { selected.value = (await request<Audit>(`/audit-logs/${encodeURIComponent(row.id)}`)).data; opened.value = true }
  catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}

function changePage(page: number) { query.page = page; void load() }
function changeSize(size: number) { query.page_size = size; changePage(1) }
onMounted(load)
</script>

<template>
  <section class="management-page">
    <div class="page-heading"><div><p class="eyebrow">OPERATION AUDIT</p><h1>操作记录</h1><p class="page-description">查看操作者、操作来源、资料差异及真实执行结果。</p></div></div>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <section class="data-panel" :aria-busy="loading">
      <form class="filters" @submit.prevent="changePage(1)">
        <input v-model="query.q" aria-label="搜索操作记录" placeholder="对象名称、动作或失败原因" maxlength="100" />
        <select v-model="query.outcome" aria-label="操作结果"><option value="">全部结果</option><option value="SUCCEEDED">成功</option><option value="FAILED">失败</option></select>
        <select v-model="query.target_type" aria-label="操作对象类型"><option value="">全部对象</option><option value="CATEGORY">采集类别</option><option value="DRIVER">司机</option><option value="VEHICLE">车辆</option><option value="UNAVAILABILITY">不可用记录</option></select>
        <input v-model="query.start_date" type="date" aria-label="审计开始日期" /><input v-model="query.end_date" type="date" aria-label="审计结束日期" />
        <ElButton native-type="submit" :loading="loading">查询</ElButton><ElButton :loading="loading" @click="load">刷新</ElButton>
      </form>
      <p v-if="loading" role="status" class="loading-note">正在加载操作记录…</p>
      <div class="table-scroll"><table class="data-table"><thead><tr><th>操作</th><th>操作者 / 来源</th><th>结果</th><th>发生时间（UTC）</th><th>操作编号</th><th>详情</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><strong>{{ row.target_label_snapshot }}</strong><small>{{ row.action_code }} · {{ row.target_type }} {{ row.target_id }}</small></td>
          <td>{{ row.actor_name_snapshot }}<small>{{ row.entry_source === 'PAGE' ? '页面' : 'Agent' }}</small></td><td><ElTag :type="row.outcome === 'SUCCEEDED' ? 'success' : 'danger'">{{ row.outcome === 'SUCCEEDED' ? '成功' : '失败' }}</ElTag></td>
          <td class="numeric">{{ row.created_at }}</td><td>{{ row.business_operation_id ?? '—' }}</td><td><ElButton link type="primary" @click="details(row)">查看详情</ElButton></td>
        </tr></tbody></table></div>
      <ElEmpty v-if="!loading && !rows.length" description="暂无符合条件的操作记录" />
      <PageNav :page="query.page" :page-size="query.page_size" :total="total" :loading="loading" @page="changePage" @size="changeSize" />
    </section>
    <ElDialog v-model="opened" title="操作记录详情" class="review-dialog">
      <template v-if="selected"><h2>{{ selected.target_label_snapshot }}</h2><p class="muted">{{ selected.created_at }} · {{ selected.actor_name_snapshot }} · {{ selected.entry_source }}</p>
        <ElAlert v-if="selected.reason" :title="selected.reason" type="error" :closable="false" />
        <ChangeTable v-if="selected.changes_json?.changes?.length" :changes="selected.changes_json.changes" />
        <div class="state-pair"><section class="state-card"><h3>操作前数据</h3><pre class="snapshot-data">{{ displayValue(selected.changes_json?.before) }}</pre></section>
          <section class="state-card"><h3>操作后数据</h3><pre class="snapshot-data">{{ displayValue(selected.changes_json?.after) }}</pre></section></div>
        <p v-if="selected.changes_json?.affected_dates?.length">关联日期 {{ selected.changes_json.affected_dates.join('、') }}</p>
        <pre v-if="selected.changes_json?.errors?.length" class="snapshot-data">{{ displayValue(selected.changes_json.errors) }}</pre>
      </template>
      <template #footer><ElButton @click="opened = false">关闭</ElButton></template>
    </ElDialog>
  </section>
</template>
