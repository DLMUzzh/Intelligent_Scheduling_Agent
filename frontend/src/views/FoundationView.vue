<script setup lang="ts">
import { onMounted } from 'vue'
import { ElAlert, ElButton, ElTag } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'
import { useLocalContext } from '../stores/context'

const local = useLocalContext()
const capabilities = [
  ['Prepare', '冻结操作内容与完整预览'],
  ['Confirm', '确认校验与事务执行'],
  ['Idempotency', '持久化请求与结果核实'],
  ['Version', '全局及对象版本校验'],
  ['Audit', '操作者、变更与结果追溯'],
]

onMounted(local.refresh)
</script>

<template>
  <section class="foundation-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">PROJECT FOUNDATION</p>
        <h1>项目基础与公共能力</h1>
        <p class="page-description">本机运行入口、数据存储与统一操作协议。</p>
      </div>
      <ElButton :loading="local.loading" @click="local.refresh">刷新连接</ElButton>
    </div>

    <ElAlert v-if="local.error" :title="local.error" type="error" :closable="false" show-icon />

    <section class="connection-card" aria-labelledby="connection-title" :aria-busy="local.loading">
      <div class="card-heading">
        <h2 id="connection-title">本机服务</h2>
        <ElTag :type="local.context ? 'success' : 'info'" effect="light">
          {{ local.loading ? '连接中' : local.context ? '已连接' : '等待连接' }}
        </ElTag>
      </div>
      <dl class="context-grid">
        <div><dt>当前操作者</dt><dd>{{ local.context?.actor_name ?? '—' }}</dd></div>
        <div><dt>业务日期 · 北京时间</dt><dd>{{ local.context?.business_date ?? '—' }}</dd></div>
        <div><dt>业务数据修订</dt><dd data-testid="revision">{{ local.revision ?? '—' }}</dd></div>
        <div><dt>通知接入</dt><dd>通知未接入</dd></div>
      </dl>
    </section>

    <section class="capability-section" aria-labelledby="capability-title">
      <div class="section-heading"><h2 id="capability-title">公共操作协议</h2><span>统一服务层</span></div>
      <ul class="capability-list">
        <li v-for="([name, description], index) in capabilities" :key="name">
          <span class="capability-number">{{ String(index + 1).padStart(2, '0') }}</span>
          <strong>{{ name }}</strong><span class="capability-description">{{ description }}</span>
        </li>
      </ul>
      <p class="phase-note">业务模块将在后续阶段通过专用适配器接入公共协议。</p>
    </section>
  </section>
</template>
