<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElAlert, ElButton } from 'element-plus'
import { listDrivers, listVehicles } from '../api/base-data'
import type { Driver, Vehicle } from '../types/base-data'
import { errorMessage } from '../utils/base-data'
const props = defineProps<{ kind: 'DRIVER' | 'VEHICLE'; selected: Driver | Vehicle | null }>()
const emit = defineEmits<{ select: [resource: Driver | Vehicle, revision: string] }>()
const rows = ref<(Driver | Vehicle)[]>([])
const query = ref('')
const page = ref(1)
const total = ref('0')
const revision = ref<string | null>(null)
const loading = ref(false)
const error = ref('')
let sequence = 0

async function load(reset = false) {
  if (reset) page.value = 1
  const current = ++sequence
  loading.value = true
  error.value = ''
  try {
    const filters = { q: query.value, page: page.value, page_size: 20 }
    const result = props.kind === 'DRIVER' ? await listDrivers(filters) : await listVehicles(filters)
    if (current !== sequence) return
    rows.value = result.data?.items ?? []
    total.value = result.data?.total ?? '0'
    revision.value = result.data_revision
  } catch (cause) { if (current === sequence) error.value = errorMessage(cause) }
  finally { if (current === sequence) loading.value = false }
}

function select(event: Event) {
  const row = rows.value.find(value => value.id === (event.target as HTMLSelectElement).value)
  if (row && revision.value) emit('select', row, revision.value)
}

function label(row: Driver | Vehicle) {
  return `${'plate_number' in row ? row.plate_number : row.name} · 编号 ${row.id}${row.is_enabled ? '' : ' · 已停用'}`
}

watch(() => props.kind, () => { query.value = ''; void load(true) })
onMounted(() => load())
</script>

<template>
  <div class="resource-picker">
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <div class="picker-search"><input v-model="query" aria-label="查找请假维修资源" maxlength="100" placeholder="名称、车牌或编号" @keydown.enter.prevent="load(true)" />
      <ElButton :loading="loading" @click="load(true)">查找资源</ElButton></div>
    <select :value="selected?.id ?? ''" aria-label="选择请假维修资源" required :disabled="loading" @change="select">
      <option value="" disabled>请选择唯一资源</option>
      <option v-if="selected && !rows.some(row => row.id === selected?.id)" :value="selected.id">{{ label(selected) }}</option>
      <option v-for="row in rows" :key="row.id" :value="row.id">{{ label(row) }}</option>
    </select>
    <div class="picker-pages"><span>共 {{ total }} 条 · 第 {{ page }} 页</span>
      <ElButton size="small" :disabled="page <= 1 || loading" @click="page--; load()">上一页资源</ElButton>
      <ElButton size="small" :disabled="BigInt(page) * 20n >= BigInt(total) || loading" @click="page++; load()">下一页资源</ElButton>
    </div>
  </div>
</template>
