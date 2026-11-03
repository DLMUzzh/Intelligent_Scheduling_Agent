<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElAlert, ElButton, ElDialog, ElEmpty, ElTag } from 'element-plus'
import { getDriver, getUnavailability, getVehicle, listUnavailability } from '../../api/base-data'
import type { Driver, Unavailability, Vehicle } from '../../types/base-data'
import { useOperation } from '../../stores/operation'
import { useLocalContext } from '../../stores/context'
import { errorMessage } from '../../utils/base-data'
import PageNav from '../../components/PageNav.vue'
import ResourcePicker from '../../components/ResourcePicker.vue'

const route = useRoute()
const local = useLocalContext()
const operations = useOperation()
const rows = ref<Unavailability[]>([])
const total = ref('0')
const loading = ref(false)
const error = ref('')
const formError = ref('')
const query = reactive({ kind: route.query.vehicle_id ? 'VEHICLE' : 'DRIVER',
  resource_id: String(route.query.driver_id ?? route.query.vehicle_id ?? ''), start_date: '', end_date: '', page: 1, page_size: 20 })
const editor = ref(false)
const editing = ref<Unavailability | null>(null)
const resource = ref<Driver | Vehicle | null>(null)
const editRevision = ref<string | null>(null)
const form = reactive({ kind: 'DRIVER' as 'DRIVER' | 'VEHICLE', start_date: '', end_date: '', reason: '' })
let sequence = 0

async function load() {
  const current = ++sequence
  loading.value = true
  error.value = ''
  try {
    const response = await listUnavailability({ page: query.page, page_size: query.page_size,
      [query.kind === 'DRIVER' ? 'driver_id' : 'vehicle_id']: query.resource_id,
      start_date: query.start_date, end_date: query.end_date })
    if (current !== sequence) return
    rows.value = response.data?.items ?? []
    total.value = response.data?.total ?? '0'
  } catch (cause) { if (current === sequence) error.value = errorMessage(cause) }
  finally { if (current === sequence) loading.value = false }
}

function selectResource(value: Driver | Vehicle, revision: string) {
  resource.value = value
  editRevision.value = revision
}

async function open(row: Unavailability | null = null, remove = false) {
  formError.value = ''
  error.value = ''
  resource.value = null
  editing.value = null
  editRevision.value = null
  form.kind = query.kind as 'DRIVER' | 'VEHICLE'
  form.start_date = form.end_date = ''
  form.reason = ''
  loading.value = true
  try {
    if (row) {
      const response = await getUnavailability(row.id)
      if (!response.data) return
      editing.value = response.data
      form.kind = response.data.driver_id ? 'DRIVER' : 'VEHICLE'
      form.start_date = response.data.start_date
      form.end_date = response.data.end_date
      form.reason = response.data.reason ?? ''
      const selected = form.kind === 'DRIVER' ? await getDriver(response.data.driver_id!) : await getVehicle(response.data.vehicle_id!)
      if (selected.data_revision !== response.data_revision) throw new Error('资料在读取期间变化，请重新打开记录')
      resource.value = selected.data
      editRevision.value = response.data_revision
    } else if (query.resource_id) {
      const selected = form.kind === 'DRIVER' ? await getDriver(query.resource_id) : await getVehicle(query.resource_id)
      resource.value = selected.data
      editRevision.value = selected.data_revision
    }
    if (remove) await stage(true)
    else editor.value = true
  } catch (cause) { error.value = errorMessage(cause) }
  finally { loading.value = false }
}

async function stage(remove = false) {
  if (!resource.value || !editRevision.value) { formError.value = '请选择唯一司机或车辆'; return }
  formError.value = ''
  if (!remove && (form.start_date > form.end_date || form.start_date <= (local.context?.business_date ?? ''))) {
    formError.value = '请设置完整的未来日期范围，结束日期不得早于开始日期'
    return
  }
  const record = editing.value
  await operations.prepare({ request_key: crypto.randomUUID(),
    action_code: `${remove ? 'DELETE' : record ? 'UPDATE' : 'CREATE'}_UNAVAILABILITY`, target_type: 'UNAVAILABILITY', target_id: record?.id ?? null,
    payload: remove ? {} : { ...(record ? {} : { [form.kind === 'DRIVER' ? 'driver_id' : 'vehicle_id']: resource.value.id }),
      start_date: form.start_date, end_date: form.end_date, reason: form.reason.trim() || null },
    expected_versions_json: { business_revision: editRevision.value,
      [form.kind === 'DRIVER' ? 'drivers' : 'vehicles']: [{ id: resource.value.id, version: resource.value.version }],
      resource_unavailability: record ? [{ id: record.id, version: record.version }] : [] },
  })
}

async function refreshBasis() {
  if (!resource.value) return
  try {
    const selected = form.kind === 'DRIVER' ? await getDriver(resource.value.id) : await getVehicle(resource.value.id)
    if (editing.value) {
      const current = await getUnavailability(editing.value.id)
      if (current.data_revision !== selected.data_revision) throw new Error('资料在读取期间变化，请再次刷新')
      editing.value = current.data
    }
    resource.value = selected.data
    editRevision.value = selected.data_revision
    formError.value = '已刷新当前版本，输入已保留。请重新查看完整变更。'
  } catch (cause) { formError.value = errorMessage(cause) }
}

function changePage(page: number) { query.page = page; void load() }
function changeSize(size: number) { query.page_size = size; changePage(1) }
watch(() => form.kind, () => { if (!editing.value) { resource.value = null; editRevision.value = null } })
watch(() => operations.completed, () => { editor.value = false; void load() })
onMounted(async () => { await local.refresh(); await load() })
</script>

<template>
  <section class="management-page">
    <div class="page-heading"><div><p class="eyebrow">RESOURCE AVAILABILITY</p><h1>请假与维修</h1>
      <p class="page-description">按整日记录不可用区间，日期范围包含首尾，重叠记录按并集计算。</p></div>
      <ElButton type="primary" :disabled="loading || operations.locked" @click="open()">新增不可用记录</ElButton>
    </div>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <section class="data-panel" :aria-busy="loading">
      <form class="filters" @submit.prevent="changePage(1)">
        <select v-model="query.kind" aria-label="资源编号类型"><option value="DRIVER">按司机编号</option><option value="VEHICLE">按车辆编号</option></select>
        <input v-model="query.resource_id" aria-label="筛选资源编号" placeholder="资源编号，可留空" inputmode="numeric" pattern="[1-9][0-9]*" />
        <label class="filter-label">相交日期<input v-model="query.start_date" aria-label="筛选开始日期" type="date" /></label>
        <input v-model="query.end_date" aria-label="筛选结束日期" type="date" />
        <ElButton native-type="submit" :loading="loading">查询</ElButton><ElButton :loading="loading" @click="load">刷新</ElButton>
      </form>
      <p v-if="loading" role="status" class="loading-note">正在加载不可用记录…</p>
      <div class="table-scroll"><table class="data-table"><thead><tr><th>资源</th><th>开始日期</th><th>结束日期</th><th>原因</th><th>编号 / 版本</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><ElTag :type="row.driver_id ? 'success' : 'warning'">{{ row.driver_id ? '请假' : '维修' }}</ElTag><small>{{ row.driver_id ? `司机 ${row.driver_id}` : `车辆 ${row.vehicle_id}` }}</small></td>
          <td class="numeric">{{ row.start_date }}</td><td class="numeric">{{ row.end_date }}</td><td class="reason-cell">{{ row.reason ?? '—' }}</td><td class="numeric">{{ row.id }} / v{{ row.version }}</td>
          <td class="row-actions"><ElButton link type="primary" :disabled="loading || operations.locked || row.start_date <= (local.context?.business_date ?? '')" @click="open(row)">编辑</ElButton>
            <ElButton link type="danger" :disabled="loading || operations.locked || row.start_date <= (local.context?.business_date ?? '')" @click="open(row, true)">取消记录</ElButton>
            <small v-if="row.start_date <= (local.context?.business_date ?? '')">日期已锁定</small></td>
        </tr></tbody></table></div>
      <ElEmpty v-if="!loading && !rows.length" description="暂无符合条件的请假或维修记录" />
      <PageNav :page="query.page" :page-size="query.page_size" :total="total" :loading="loading" @page="changePage" @size="changeSize" />
    </section>
    <p class="management-note">当天突发情况线下处理。编辑和取消会校验原区间，影响未来正式安排时会列出日期并拒绝生效。</p>
    <ElDialog v-model="editor" :title="editing ? '编辑不可用记录' : '新增不可用记录'" class="editor-dialog" :close-on-click-modal="false">
      <ElAlert v-if="formError" :title="formError" type="warning" :closable="false" />
      <form id="unavailability-form" class="edit-form form-grid" @submit.prevent="stage()">
        <label class="full-span">记录类型<select v-model="form.kind" aria-label="记录类型" :disabled="Boolean(editing)"><option value="DRIVER">司机请假</option><option value="VEHICLE">车辆维修</option></select></label>
        <div v-if="editing && resource" class="full-span selected-resource">{{ form.kind === 'DRIVER' ? '司机' : '车辆' }} {{ resource.id }} · {{ 'plate_number' in resource ? resource.plate_number : resource.name }}</div>
        <ResourcePicker v-else class="full-span" :kind="form.kind" :selected="resource" @select="selectResource" />
        <label>开始日期<input v-model="form.start_date" type="date" aria-label="不可用开始日期" required /></label>
        <label>结束日期<input v-model="form.end_date" type="date" aria-label="不可用结束日期" required /></label>
        <label class="full-span">原因<textarea v-model="form.reason" rows="3" aria-label="不可用原因" maxlength="2000"></textarea></label>
      </form>
      <template #footer><ElButton :disabled="operations.locked" @click="refreshBasis">刷新版本并保留输入</ElButton><ElButton @click="editor = false">取消</ElButton>
        <ElButton type="primary" native-type="submit" form="unavailability-form" :disabled="operations.locked">查看变更</ElButton></template>
    </ElDialog>
  </section>
</template>
