<script setup lang="ts">
import { computed } from 'vue'
import { ElButton } from 'element-plus'
const props = defineProps<{ page: number; pageSize: number; total: string; loading: boolean }>()
const emit = defineEmits<{ page: [value: number]; size: [value: number] }>()
const hasNext = computed(() => BigInt(props.page) * BigInt(props.pageSize) < BigInt(props.total))
</script>

<template>
  <footer class="page-nav">
    <span>共 {{ total }} 条 · 第 {{ page }} 页</span>
    <div class="nav-actions">
      <select aria-label="每页条数" :value="pageSize" :disabled="loading" @change="emit('size', Number(($event.target as HTMLSelectElement).value))">
        <option :value="20">20 条 / 页</option><option :value="50">50 条 / 页</option><option :value="100">100 条 / 页</option>
      </select>
      <ElButton :disabled="page <= 1 || loading" @click="emit('page', page - 1)">上一页</ElButton>
      <ElButton :disabled="!hasNext || loading" @click="emit('page', page + 1)">下一页</ElButton>
    </div>
  </footer>
</template>
