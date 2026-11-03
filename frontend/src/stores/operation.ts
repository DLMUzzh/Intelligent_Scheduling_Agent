import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError, TransportError } from '../api/client'
import { executeOperation, findOperation, getOperation, prepareOperation } from '../api/operations'
import type { OperationView, PrepareInput } from '../types/api'
import { errorMessage } from '../utils/base-data'

const storageKey = 'fleetwise.pending-operation'

export const useOperation = defineStore('operation', () => {
  const input = ref<PrepareInput | null>(null)
  const operation = ref<OperationView | null>(null)
  const visible = ref(false)
  const busy = ref(false)
  const uncertain = ref(false)
  const executionRequested = ref(false)
  const error = ref('')
  const completed = ref(0)
  const locked = computed(() => busy.value || uncertain.value || operation.value?.status === 'PENDING')
  const canClose = computed(() => !busy.value && !uncertain.value && !(executionRequested.value && operation.value?.status === 'PENDING'))

  function persist() {
    try {
      if (input.value && (uncertain.value || operation.value?.status === 'PENDING')) {
        sessionStorage.setItem(storageKey, JSON.stringify({ input: input.value, executionRequested: executionRequested.value }))
      } else sessionStorage.removeItem(storageKey)
    } catch { /* The server remains the source of truth when browser storage is unavailable. */ }
  }

  function accept(value: OperationView | null) {
    operation.value = value
    uncertain.value = false
    if (value?.status === 'SUCCEEDED' || value?.status === 'FAILED') executionRequested.value = false
    if (value?.status === 'SUCCEEDED') completed.value++
    if (value?.status === 'FAILED') error.value = value.error_message ?? '操作未生效'
    persist()
  }

  function reject(cause: unknown) {
    error.value = errorMessage(cause)
    if (cause instanceof ApiError && cause.response.data && typeof cause.response.data === 'object' && 'status' in cause.response.data) {
      accept(cause.response.data as OperationView)
    } else {
      uncertain.value = cause instanceof TransportError || (cause instanceof ApiError && cause.status >= 500)
      persist()
    }
  }

  async function prepare(value: PrepareInput) {
    if (locked.value) { visible.value = true; return false }
    input.value = value
    operation.value = null
    executionRequested.value = false
    error.value = ''
    busy.value = visible.value = true
    // Retain the exact key and input before sending a request that may lose its response.
    uncertain.value = true
    persist()
    try {
      accept((await prepareOperation(value)).data)
      return true
    } catch (cause) {
      reject(cause)
      return false
    } finally { busy.value = false }
  }

  async function confirm() {
    if (!operation.value || busy.value || uncertain.value) return
    error.value = ''
    busy.value = true
    executionRequested.value = true
    uncertain.value = true
    persist()
    try { accept((await executeOperation(operation.value, true)).data) }
    catch (cause) { reject(cause) }
    finally { busy.value = false }
  }

  async function verify() {
    if (!input.value || busy.value) return
    busy.value = true
    error.value = ''
    try {
      const result = operation.value
        ? (await getOperation(operation.value.id)).data
        : (await findOperation(input.value.request_key)).data?.items[0] ?? null
      accept(result)
      if (result?.status === 'PENDING' && executionRequested.value) {
        error.value = '尚无可见终态。请继续核实，或核实并执行同一绑定操作。当前请求键保持锁定。'
      }
      if (!result) {
        uncertain.value = true
        error.value = '暂未查询到操作记录。原请求结束后，可使用下方按钮核实原请求，幂等键保持一致。'
        persist()
      }
    } catch (cause) { uncertain.value = true; error.value = errorMessage(cause); persist() }
    finally { busy.value = false }
  }

  async function verifyPreparation() {
    if (!input.value || busy.value || operation.value) return
    busy.value = true
    error.value = ''
    try { accept((await prepareOperation(input.value)).data) }
    catch (cause) { reject(cause) }
    finally { busy.value = false }
  }

  function close() {
    if (!canClose.value) return
    visible.value = false
    operation.value = null
    input.value = null
    persist()
  }

  async function restore() {
    try {
      const saved = sessionStorage.getItem(storageKey)
      if (!saved) return
      const stored = JSON.parse(saved) as { input: PrepareInput; executionRequested: boolean }
      input.value = stored.input
      executionRequested.value = stored.executionRequested
      uncertain.value = visible.value = true
      await verify()
    } catch { error.value = '无法恢复浏览器中的操作编号，请按原请求键查询操作记录' }
  }

  return { input, operation, visible, busy, uncertain, executionRequested, error, completed, locked, canClose, prepare, confirm, verify,
    verifyPreparation, close, restore }
})
