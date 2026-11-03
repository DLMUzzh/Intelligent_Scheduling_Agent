<script setup lang="ts">
import { computed } from 'vue'
import { ElAlert, ElButton, ElDialog, ElTag } from 'element-plus'
import { useOperation } from '../stores/operation'
import type { FieldChange, RelatedChange } from '../types/base-data'
import { displayValue, labels } from '../utils/base-data'
import ChangeTable from './ChangeTable.vue'

const operations = useOperation()
const summary = computed(() => operations.operation?.summary_json)
const changes = computed(() => (summary.value?.changes ?? []) as unknown as FieldChange[])
const related = computed(() => (summary.value?.related_changes ?? []) as unknown as RelatedChange[])
const stateLabel = computed(() => operations.operation?.status === 'SUCCEEDED' ? '已生效'
  : operations.operation?.status === 'FAILED' ? '未生效' : '待确认')
</script>

<template>
  <ElDialog :model-value="operations.visible" title="操作预览与确认" class="review-dialog"
    :close-on-click-modal="false" :close-on-press-escape="false" :show-close="false" destroy-on-close>
    <ElAlert v-if="operations.error" :title="operations.error" type="error" :closable="false" show-icon />
    <ElAlert v-if="operations.uncertain" title="操作结果待核实，请保留当前请求键并查询真实状态。" type="warning" :closable="false" />
    <div v-if="operations.busy" role="status" class="loading-note">正在处理，请稍候…</div>
    <template v-if="operations.operation && summary">
      <div class="review-title"><h2>{{ summary.title }}</h2><ElTag>{{ stateLabel }}</ElTag></div>
      <p class="muted small">操作编号 {{ operations.operation.id }} · 请求键 {{ operations.operation.request_key }}</p>
      <div class="state-pair">
        <section v-for="side in (['before', 'after'] as const)" :key="side" class="state-card">
          <h3>{{ side === 'before' ? '变更前' : '变更后' }}</h3>
          <dl v-if="summary[side] && typeof summary[side] === 'object' && !Array.isArray(summary[side])" class="detail-list">
            <div v-for="(value, field) in (summary[side] as Record<string, unknown>)" :key="field">
              <dt>{{ labels[field] ?? (field === 'id' ? '编号' : field) }}</dt><dd>{{ displayValue(value) }}</dd>
            </div>
          </dl>
          <p v-else class="muted">{{ side === 'before' ? '新增资料' : '删除资料' }}</p>
        </section>
      </div>
      <ChangeTable v-if="changes.length" :changes="changes" />
      <details v-if="Array.isArray(summary.affected_dates) && summary.affected_dates.length" open>
        <summary>受影响日期（{{ summary.affected_dates.length }}）</summary>
        <p class="dates-list">{{ summary.affected_dates.join('、') }}</p>
      </details>
      <details v-for="item in related" :key="item.plan_day_id ?? item.work_date" open>
        <summary>{{ item.work_date }} · 关联日期编号 {{ item.plan_day_id }}</summary>
        <ChangeTable :changes="item.changes" />
      </details>
      <ElAlert v-if="operations.operation.status === 'FAILED'" title="请刷新资料，保留编辑内容并重新查看变更。" type="warning" :closable="false" />
    </template>
    <template #footer>
      <ElButton :disabled="!operations.canClose" @click="operations.close">
        {{ operations.operation?.status === 'PENDING' ? '返回编辑' : '关闭' }}
      </ElButton>
      <ElButton v-if="operations.uncertain" :loading="operations.busy" @click="operations.verify">核实结果</ElButton>
      <ElButton v-if="operations.uncertain && !operations.operation" :disabled="operations.busy" @click="operations.verifyPreparation">按原请求核实准备</ElButton>
      <ElButton v-if="operations.operation?.status === 'PENDING' && !operations.uncertain" type="primary"
        :loading="operations.busy" @click="operations.confirm">{{ operations.executionRequested ? '核实并执行原操作' : '保存并生效' }}</ElButton>
    </template>
  </ElDialog>
</template>
