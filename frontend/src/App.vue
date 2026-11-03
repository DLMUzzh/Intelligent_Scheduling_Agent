<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { ElButton } from 'element-plus'
import OperationReview from './components/OperationReview.vue'
import { useOperation } from './stores/operation'
const operations = useOperation()
onMounted(operations.restore)
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" aria-label="应用信息">
      <div class="brand-mark" aria-hidden="true">F</div>
      <div class="brand-name">Fleetwise</div>
      <p class="brand-subtitle">司机智能排班</p>
      <div class="sidebar-rule"></div>
      <span class="section-label">车队管理 / 02</span>
      <nav class="main-nav" aria-label="主导航">
        <RouterLink to="/">项目基础与公共能力</RouterLink>
        <RouterLink to="/categories">采集类别</RouterLink>
        <RouterLink to="/resources">车队资源</RouterLink>
        <RouterLink to="/unavailability">请假与维修</RouterLink>
        <RouterLink to="/logs">操作记录</RouterLink>
      </nav>
      <p class="sidebar-note">Windows 本机运行<br />固定车队长身份</p>
    </aside>
    <main class="workspace">
      <header class="topbar">
        <span>Fleetwise 工作空间</span>
        <span class="local-indicator"><i></i> 本机环境</span>
      </header>
      <RouterView />
      <div v-if="operations.locked && !operations.visible" class="pending-banner"><ElButton @click="operations.visible = true">查看待核实操作</ElButton></div>
    </main>
    <OperationReview />
  </div>
</template>
