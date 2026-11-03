<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElAlert, ElButton, ElDialog, ElEmpty, ElTag } from 'element-plus'
import { listCategories } from '../../api/base-data'
import type { Category, Mode } from '../../types/base-data'
import { useOperation } from '../../stores/operation'
import { errorMessage } from '../../utils/base-data'
import PageNav from '../../components/PageNav.vue'

const operations = useOperation()
const rows = ref<Category[]>([])
const revision = ref<string | null>(null)
const loading = ref(false)
const error = ref('')
const query = reactive({ q: '', task_mode: '', page: 1, page_size: 20 })
const total = ref('0')
const editor = ref(false)
const editing = ref<Category | null>(null)
const form = reactive({ task_mode: 'TAG' as Mode, name: '' })
let querySequence = 0

async function load() {
  const sequence = ++querySequence
  loading.value = true
  error.value = ''
  try {
    const result = await listCategories(query)
    if (sequence !== querySequence) return
    rows.value = result.data?.items ?? []
    total.value = result.data?.total ?? '0'
    revision.value = result.data_revision
  } catch (cause) { if (sequence === querySequence) error.value = errorMessage(cause) }
  finally { if (sequence === querySequence) loading.value = false }
}

function open(row: Category | null = null) {
  editing.value = row
  form.task_mode = row?.task_mode ?? 'TAG'
  form.name = row?.name ?? ''
  editor.value = true
}

async function stage(remove = false, row = editing.value) {
  if (!revision.value) return
  await operations.prepare({
    request_key: crypto.randomUUID(), action_code: `${remove ? 'DELETE' : row ? 'UPDATE' : 'CREATE'}_CATEGORY`,
    target_type: 'CATEGORY', target_id: row?.id ?? null,
    payload: remove ? {} : row ? { name: form.name.trim() } : { task_mode: form.task_mode, name: form.name.trim() },
    expected_versions_json: { business_revision: revision.value,
      collection_categories: row ? [{ id: row.id, version: row.version }] : [] },
  })
}

async function refreshBasis() {
  await load()
  if (editing.value) {
    const current = rows.value.find(row => row.id === editing.value?.id)
    if (!current) { error.value = '当前列表未找到编辑对象，请重新定位类别'; return }
    editing.value = current
  }
}

function changePage(page: number) { query.page = page; void load() }
function changeSize(size: number) { query.page_size = size; changePage(1) }
watch(() => operations.completed, () => { editor.value = false; void load() })
onMounted(load)
</script>

<template>
  <section class="management-page">
    <div class="page-heading"><div><p class="eyebrow">COLLECTION CATALOG</p><h1>采集类别</h1>
      <p class="page-description">分别维护 Tag 和道路类别，同模式名称唯一。</p></div>
      <ElButton type="primary" :disabled="loading || !revision || operations.locked" @click="open()">新增类别</ElButton>
    </div>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <section class="data-panel" :aria-busy="loading">
      <form class="filters" @submit.prevent="changePage(1)">
        <input v-model="query.q" aria-label="搜索类别" maxlength="100" placeholder="搜索类别名称" />
        <select v-model="query.task_mode" aria-label="采集模式"><option value="">全部模式</option><option value="TAG">Tag 类别</option><option value="ROAD">道路类别</option></select>
        <ElButton native-type="submit" :loading="loading">查询</ElButton><ElButton :loading="loading" @click="load">刷新</ElButton>
      </form>
      <p v-if="loading" role="status" class="loading-note">正在加载类别…</p>
      <div class="table-scroll"><table class="data-table"><thead><tr><th>类别名称</th><th>模式</th><th>编号 / 版本</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><strong>{{ row.name }}</strong></td><td><ElTag :type="row.task_mode === 'TAG' ? 'success' : 'info'">{{ row.task_mode === 'TAG' ? 'Tag' : '道路' }}</ElTag></td>
          <td class="numeric">{{ row.id }} / v{{ row.version }}</td><td class="row-actions">
            <ElButton link type="primary" :disabled="loading || operations.locked" @click="open(row)">更名</ElButton>
            <ElButton link type="danger" :disabled="loading || operations.locked" @click="stage(true, row)">删除</ElButton>
          </td></tr></tbody></table></div>
      <ElEmpty v-if="!loading && !rows.length" description="暂无符合条件的采集类别" />
      <PageNav :page="query.page" :page-size="query.page_size" :total="total" :loading="loading" @page="changePage" @size="changeSize" />
    </section>
    <p class="management-note">被需求、草稿或正式历史引用的类别会保留。更名将展示未来关联日期的完整变化。</p>
    <ElDialog v-model="editor" :title="editing ? '类别更名' : '新增类别'" class="editor-dialog" :close-on-click-modal="false">
      <form id="category-form" class="edit-form" @submit.prevent="stage()">
        <label>采集模式<select v-model="form.task_mode" :disabled="Boolean(editing)" aria-label="类别模式"><option value="TAG">Tag</option><option value="ROAD">道路</option></select></label>
        <label>类别名称<input v-model="form.name" aria-label="类别名称" required maxlength="100" pattern=".*\S.*" /></label>
      </form>
      <template #footer><ElButton :disabled="operations.locked" @click="refreshBasis">刷新版本并保留输入</ElButton><ElButton @click="editor = false">取消</ElButton><ElButton type="primary" native-type="submit" form="category-form" :disabled="operations.locked">查看变更</ElButton></template>
    </ElDialog>
  </section>
</template>
