<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" aria-label="应用信息">
      <div class="brand-mark" aria-hidden="true">F</div>
      <div class="brand-name">Fleetwise</div>
      <p class="brand-subtitle">司机智能排班</p>
      <div class="sidebar-rule"></div>
      <span class="section-label">开发阶段 / 01</span>
      <div class="active-section">项目基础与公共能力</div>
      <p class="sidebar-note">Windows 本机运行<br />固定车队长身份</p>
    </aside>
    <main class="workspace">
      <header class="topbar">
        <span>Fleetwise 工作空间</span>
        <span class="local-indicator"><i></i> 本机环境</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>
