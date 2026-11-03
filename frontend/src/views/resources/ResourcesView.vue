<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ElAlert, ElButton, ElDialog, ElEmpty, ElTag } from 'element-plus'
import { getDriver, getVehicle, listDrivers, listVehicles } from '../../api/base-data'
import type { Capacities, CapacityField, Driver, Efficiency, Flag, Vehicle } from '../../types/base-data'
import { capacityFields, shifts } from '../../types/base-data'
import { useOperation } from '../../stores/operation'
import { useLocalContext } from '../../stores/context'
import { efficiencyLabels, errorMessage, kilometersToMeters, metersToKilometers, uint } from '../../utils/base-data'
import PageNav from '../../components/PageNav.vue'

const route = useRoute()
const operations = useOperation()
const local = useLocalContext()
const kind = ref<'DRIVER' | 'VEHICLE'>(route.query.tab === 'vehicles' ? 'VEHICLE' : 'DRIVER')
const drivers = ref<Driver[]>([])
const vehicles = ref<Vehicle[]>([])
const loading = ref(false)
const error = ref('')
const formError = ref('')
const formNotice = ref('')
const revision = ref<string | null>(null)
const editRevision = ref<string | null>(null)
const total = ref('0')
const query = reactive({ q: '', efficiency_level: '', is_enabled: '', is_available: '', work_date: '', page: 1, page_size: 20 })
const editor = ref(false)
const detail = ref(false)
const selected = ref<Driver | Vehicle | null>(null)
const form = reactive({ name: '', phone: '', efficiency_level: 'MEDIUM' as Efficiency, is_enabled: 1 as Flag,
  can_morning: 1 as Flag, can_middle: 1 as Flag, can_evening: 1 as Flag, plate_number: '', notes: '',
  capacities: Object.fromEntries(capacityFields.map(field => [field, '0'])) as Capacities })
const isDriver = computed(() => kind.value === 'DRIVER')
let querySequence = 0

async function load() {
  const sequence = ++querySequence
  loading.value = true
  error.value = ''
  const { efficiency_level, ...common } = query
  try {
    const result = isDriver.value ? await listDrivers({ ...common, efficiency_level }) : await listVehicles(common)
    if (sequence !== querySequence) return
    if (isDriver.value) drivers.value = (result.data?.items ?? []) as Driver[]
    else vehicles.value = (result.data?.items ?? []) as Vehicle[]
    total.value = result.data?.total ?? '0'
    revision.value = result.data_revision
  } catch (cause) { if (sequence === querySequence) error.value = errorMessage(cause) }
  finally { if (sequence === querySequence) loading.value = false }
}

async function open(row: Driver | Vehicle | null = null, readonly = false) {
  formError.value = ''
  formNotice.value = ''
  error.value = ''
  selected.value = null
  if (row) {
    loading.value = true
    try {
      const response = isDriver.value ? await getDriver(row.id, query.work_date) : await getVehicle(row.id, query.work_date)
      selected.value = response.data
      editRevision.value = response.data_revision
    } catch (cause) { error.value = errorMessage(cause); return }
    finally { loading.value = false }
  } else editRevision.value = revision.value
  const current = selected.value
  form.name = current?.name ?? ''
  form.is_enabled = current?.is_enabled ?? 1
  if (isDriver.value) {
    const driver = current as Driver | null
    form.phone = driver?.phone ?? ''
    form.efficiency_level = driver?.efficiency_level ?? 'MEDIUM'
    for (const shift of shifts) form[`can_${shift.code}`] = driver?.[`can_${shift.code}`] ?? 1
  } else {
    const vehicle = current as Vehicle | null
    form.plate_number = vehicle?.plate_number ?? ''
    form.notes = vehicle?.notes ?? ''
    for (const field of capacityFields) {
      const value = vehicle?.[field] ?? '0'
      form.capacities[field] = field.endsWith('road_meters') ? metersToKilometers(value) : value
    }
  }
  detail.value = readonly
  editor.value = !readonly
}

async function stage(verb?: 'DELETE' | 'UPDATE', row = selected.value, patch?: { is_enabled: Flag }) {
  const basis = verb ? revision.value : editRevision.value
  if (!basis) return
  formError.value = ''
  try {
    let payload: Record<string, string | number | null> = {}
    if (verb !== 'DELETE') {
      if (patch) payload = patch
      else if (isDriver.value) payload = { name: form.name.trim(), phone: form.phone.trim() || null,
        efficiency_level: form.efficiency_level, is_enabled: form.is_enabled,
        can_morning: form.can_morning, can_middle: form.can_middle, can_evening: form.can_evening }
      else {
        payload = { plate_number: form.plate_number.trim(), name: form.name.trim() || null,
          notes: form.notes.trim() || null, is_enabled: form.is_enabled }
        for (const field of capacityFields) payload[field] = field.endsWith('road_meters')
          ? kilometersToMeters(form.capacities[field]) : uint(form.capacities[field])
      }
    }
    const action = verb ?? (row ? 'UPDATE' : 'CREATE')
    await operations.prepare({ request_key: crypto.randomUUID(), action_code: `${action}_${kind.value}`,
      target_type: kind.value, target_id: row?.id ?? null, payload,
      expected_versions_json: { business_revision: basis,
        [isDriver.value ? 'drivers' : 'vehicles']: row ? [{ id: row.id, version: row.version }] : [] },
    })
  } catch (cause) { formError.value = errorMessage(cause) }
}

async function refreshBasis() {
  try {
    if (selected.value) {
      const response = isDriver.value ? await getDriver(selected.value.id, query.work_date) : await getVehicle(selected.value.id, query.work_date)
      selected.value = response.data
      editRevision.value = response.data_revision
    } else {
      await local.refresh()
      if (!local.revision) throw new Error(local.error)
      editRevision.value = local.revision
    }
    formError.value = ''
    formNotice.value = '已刷新当前版本，输入已保留。请重新查看完整变更。'
  } catch (cause) { formError.value = errorMessage(cause) }
}

function changePage(page: number) { query.page = page; void load() }
function changeSize(size: number) { query.page_size = size; changePage(1) }
function switchKind(value: 'DRIVER' | 'VEHICLE') { kind.value = value; drivers.value = []; vehicles.value = []; changePage(1) }
watch(() => operations.completed, () => { editor.value = false; detail.value = false; void load() })
onMounted(async () => { await local.refresh(); query.work_date = local.context?.business_date ?? ''; await load() })
</script>

<template>
  <section class="management-page">
    <div class="page-heading"><div><p class="eyebrow">FLEET RESOURCES</p><h1>车队资源</h1>
      <p class="page-description">维护司机资格、车辆容量与启用状态，按日期查看整日可用性。</p></div>
      <ElButton type="primary" :disabled="loading || !revision || operations.locked" @click="open()">{{ isDriver ? '新增司机' : '新增车辆' }}</ElButton>
    </div>
    <div class="resource-tabs"><div class="tab-switch" role="group" aria-label="资源类型">
      <button :class="{ active: isDriver }" @click="switchKind('DRIVER')">司机资料</button>
      <button :class="{ active: !isDriver }" @click="switchKind('VEHICLE')">车辆资料</button>
    </div><RouterLink to="/categories">管理采集类别 ↗</RouterLink></div>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <section class="data-panel" :aria-busy="loading">
      <form class="filters" @submit.prevent="changePage(1)">
        <input v-model="query.q" aria-label="搜索资源" maxlength="100" :placeholder="isDriver ? '姓名 / 司机编号' : '车牌 / 名称 / 车辆编号'" />
        <label class="filter-label">可用日期<input v-model="query.work_date" type="date" aria-label="可用日期" /></label>
        <select v-if="isDriver" v-model="query.efficiency_level" aria-label="效率筛选"><option value="">全部效率</option><option value="HIGH">高效率</option><option value="MEDIUM">中效率</option><option value="LOW">低效率</option></select>
        <select v-model="query.is_enabled" aria-label="启用筛选"><option value="">全部启用状态</option><option value="1">已启用</option><option value="0">已停用</option></select>
        <select v-model="query.is_available" aria-label="可用筛选"><option value="">全部可用状态</option><option value="1">可用</option><option value="0">不可用</option></select>
        <ElButton native-type="submit" :loading="loading">查询</ElButton><ElButton :loading="loading" @click="load">刷新</ElButton>
      </form>
      <p v-if="loading" role="status" class="loading-note">正在加载资源…</p>
      <div class="table-scroll"><table class="data-table resource-table">
        <thead><tr><th>{{ isDriver ? '司机' : '车辆' }}</th><th>{{ isDriver ? '效率 / 联系方式' : '三班容量 · 早 / 中 / 晚' }}</th>
          <th>{{ isDriver ? '班次资格' : '车辆名称' }}</th><th>可用状态</th><th>有效正式班次</th><th>操作</th></tr></thead>
        <tbody v-if="isDriver"><tr v-for="row in drivers" :key="row.id">
          <td><div class="resource-name"><span class="person-avatar">{{ row.name.slice(0, 1) }}</span><div><strong>{{ row.name }}</strong><small>司机 {{ row.id }} · v{{ row.version }}</small></div></div></td>
          <td><ElTag :type="row.efficiency_level === 'HIGH' ? 'success' : row.efficiency_level === 'MEDIUM' ? 'warning' : 'info'">{{ efficiencyLabels[row.efficiency_level] }}效率</ElTag><small>{{ row.phone ?? '未填写联系方式' }}</small></td>
          <td>{{ shifts.filter(shift => row[`can_${shift.code}`]).map(shift => shift.label).join(' · ') || '无班次资格' }}</td>
          <td><ElTag :type="row.is_available ? 'success' : 'info'">{{ !row.is_enabled ? '已停用' : row.unavailability_ids.length ? '请假中' : '可用' }}</ElTag></td>
          <td class="numeric">{{ row.scheduled_shift_count }} 班</td>
          <td class="row-actions"><ElButton link @click="open(row, true)">详情</ElButton><ElButton link type="primary" :disabled="loading || operations.locked" @click="open(row)">编辑</ElButton>
            <RouterLink :to="{ path: '/unavailability', query: { driver_id: row.id } }">请假</RouterLink>
            <ElButton link :disabled="loading || operations.locked" @click="stage('UPDATE', row, { is_enabled: row.is_enabled ? 0 : 1 })">{{ row.is_enabled ? '停用' : '启用' }}</ElButton>
            <ElButton link type="danger" :disabled="loading || operations.locked" @click="stage('DELETE', row)">删除</ElButton></td>
        </tr></tbody>
        <tbody v-else><tr v-for="row in vehicles" :key="row.id">
          <td><strong>{{ row.plate_number }}</strong><small>车辆 {{ row.id }} · v{{ row.version }}</small></td>
          <td class="capacity-cell"><span>Tag {{ shifts.map(shift => row[`${shift.code}_max_tag_count`]).join(' / ') }} 个</span>
            <small>道路 {{ shifts.map(shift => metersToKilometers(row[`${shift.code}_max_road_meters`])).join(' / ') }} km</small></td>
          <td>{{ row.name ?? '—' }}</td><td><ElTag :type="row.is_available ? 'success' : 'info'">{{ !row.is_enabled ? '已停用' : row.unavailability_ids.length ? '维修中' : '可用' }}</ElTag></td>
          <td class="numeric">{{ row.scheduled_shift_count }} 班</td>
          <td class="row-actions"><ElButton link @click="open(row, true)">详情</ElButton><ElButton link type="primary" :disabled="loading || operations.locked" @click="open(row)">编辑</ElButton>
            <RouterLink :to="{ path: '/unavailability', query: { vehicle_id: row.id } }">维修</RouterLink>
            <ElButton link :disabled="loading || operations.locked" @click="stage('UPDATE', row, { is_enabled: row.is_enabled ? 0 : 1 })">{{ row.is_enabled ? '停用' : '启用' }}</ElButton>
            <ElButton link type="danger" :disabled="loading || operations.locked" @click="stage('DELETE', row)">删除</ElButton></td>
        </tr></tbody>
      </table></div>
      <ElEmpty v-if="!loading && !(isDriver ? drivers : vehicles).length" :description="isDriver ? '暂无符合条件的司机' : '暂无符合条件的车辆'" />
      <PageNav :page="query.page" :page-size="query.page_size" :total="total" :loading="loading" @page="changePage" @size="changeSize" />
    </section>
    <p class="management-note">可用性根据启用状态和整日请假 / 维修计算。被任务或正式历史引用的资源保留，未来正式安排会保护所需资格及容量。</p>
    <ElDialog v-model="editor" :title="`${selected ? '编辑' : '新增'}${isDriver ? '司机' : '车辆'}`" class="editor-dialog" :close-on-click-modal="false">
      <ElAlert v-if="formError" :title="formError" type="error" :closable="false" />
      <ElAlert v-if="formNotice" :title="formNotice" type="info" :closable="false" />
      <form id="resource-form" class="edit-form form-grid" @submit.prevent="stage()">
        <template v-if="isDriver">
          <label>司机姓名<input v-model="form.name" aria-label="司机姓名" required maxlength="100" pattern=".*\S.*" /></label>
          <label>联系方式<input v-model="form.phone" aria-label="联系方式" maxlength="40" /></label>
          <label>效率等级<select v-model="form.efficiency_level" aria-label="效率等级"><option value="HIGH">高</option><option value="MEDIUM">中</option><option value="LOW">低</option></select></label>
          <fieldset class="full-span"><legend>班次资格</legend><label v-for="shift in shifts" :key="shift.code" class="check-label">
            <input v-model="form[`can_${shift.code}`]" type="checkbox" :true-value="1" :false-value="0" :aria-label="`${shift.label}资格`" />{{ shift.label }}
          </label></fieldset>
        </template>
        <template v-else>
          <label>车牌号<input v-model="form.plate_number" aria-label="车牌号" required maxlength="30" pattern=".*\S.*" /></label>
          <label>车辆名称<input v-model="form.name" aria-label="车辆名称" maxlength="100" /></label>
          <div class="capacity-editor full-span"><div class="capacity-head"><span>班次</span><span>Tag 容量 · 个</span><span>道路容量 · 公里</span></div>
            <div v-for="shift in shifts" :key="shift.code" class="capacity-row"><strong>{{ shift.label }}</strong>
              <input v-model="form.capacities[`${shift.code}_max_tag_count` as CapacityField]" :aria-label="`${shift.label} Tag 容量`" inputmode="numeric" required pattern="(0|[1-9][0-9]*)" />
              <input v-model="form.capacities[`${shift.code}_max_road_meters` as CapacityField]" :aria-label="`${shift.label}道路容量`" inputmode="decimal" required pattern="(0|[1-9][0-9]*)(\.[0-9]{1,3})?" />
            </div>
          </div><p class="form-hint full-span">容量允许为零。道路最多三位小数，按整数米精确保存。</p>
          <label class="full-span">备注<textarea v-model="form.notes" aria-label="车辆备注" maxlength="2000" rows="3"></textarea></label>
        </template>
        <label class="check-label full-span"><input v-model="form.is_enabled" type="checkbox" :true-value="1" :false-value="0" aria-label="启用资料" />启用</label>
      </form>
      <template #footer><ElButton :disabled="operations.locked" @click="refreshBasis">刷新版本并保留输入</ElButton><ElButton @click="editor = false">取消</ElButton><ElButton type="primary" native-type="submit" form="resource-form" :disabled="operations.locked">查看变更</ElButton></template>
    </ElDialog>
    <ElDialog v-model="detail" :title="isDriver ? '司机详情' : '车辆详情'" class="editor-dialog">
      <dl v-if="selected" class="detail-list">
        <div><dt>编号</dt><dd>{{ selected.id }} · v{{ selected.version }}</dd></div>
        <div><dt>名称</dt><dd>{{ selected.name ?? '—' }}</dd></div>
        <div><dt>指定日期</dt><dd>{{ selected.work_date }}</dd></div>
        <div><dt>启用状态</dt><dd>{{ selected.is_enabled ? '启用' : '停用' }}</dd></div>
        <template v-if="isDriver"><div><dt>效率等级</dt><dd>{{ efficiencyLabels[(selected as Driver).efficiency_level] }}</dd></div>
          <div><dt>联系方式</dt><dd>{{ (selected as Driver).phone ?? '—' }}</dd></div>
          <div><dt>班次资格</dt><dd>{{ shifts.filter(shift => (selected as Driver)[`can_${shift.code}`]).map(shift => shift.label).join(' · ') || '无班次资格' }}</dd></div></template>
        <template v-else><div><dt>车牌号</dt><dd>{{ (selected as Vehicle).plate_number }}</dd></div>
          <div v-for="shift in shifts" :key="shift.code"><dt>{{ shift.label }}容量</dt><dd>Tag {{ (selected as Vehicle)[`${shift.code}_max_tag_count`] }} 个 · 道路 {{ metersToKilometers((selected as Vehicle)[`${shift.code}_max_road_meters`]) }} km</dd></div>
          <div><dt>备注</dt><dd>{{ (selected as Vehicle).notes ?? '—' }}</dd></div></template>
        <div><dt>有效正式班次</dt><dd>{{ selected.scheduled_shift_count }}</dd></div>
        <div><dt>创建时间</dt><dd>{{ selected.created_at }}</dd></div><div><dt>更新时间</dt><dd>{{ selected.updated_at }}</dd></div>
      </dl>
      <template #footer><ElButton @click="detail = false">关闭</ElButton></template>
    </ElDialog>
  </section>
</template>
