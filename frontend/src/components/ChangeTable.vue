<script setup lang="ts">
import type { FieldChange } from '../types/base-data'
import { displayValue, labels } from '../utils/base-data'
defineProps<{ changes: FieldChange[] }>()
</script>

<template>
  <div class="table-scroll">
    <table class="data-table change-table">
      <thead><tr><th>变更字段</th><th>变更前</th><th>变更后</th></tr></thead>
      <tbody><tr v-for="change in changes" :key="change.field">
        <td>{{ labels[change.field] ?? change.label }}</td>
        <td><pre>{{ displayValue(change.before) }}</pre></td>
        <td><pre>{{ displayValue(change.after) }}</pre></td>
      </tr></tbody>
    </table>
  </div>
</template>
