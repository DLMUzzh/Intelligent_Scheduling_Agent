import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api/client'
import type { LocalContext } from '../types/api'

export const useLocalContext = defineStore('local-context', () => {
  const context = ref<LocalContext | null>(null)
  const revision = ref<string | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function refresh() {
    loading.value = true
    error.value = ''
    try {
      const response = await request<LocalContext>('/context')
      context.value = response.data
      revision.value = response.data_revision
    } catch (cause) {
      context.value = null
      revision.value = null
      error.value = cause instanceof Error ? cause.message : '本机服务暂不可用'
    } finally {
      loading.value = false
    }
  }

  return { context, revision, loading, error, refresh }
})
