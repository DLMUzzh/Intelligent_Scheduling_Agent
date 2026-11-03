import { request } from './client'
import type { OperationView, Page, PrepareInput } from '../types/api'

export function prepareOperation(input: PrepareInput) {
  return request<OperationView>('/operations', input)
}

export function getOperation(operationId: string) {
  return request<OperationView>(`/operations/${encodeURIComponent(operationId)}`)
}

export function findOperation(requestKey: string) {
  return request<Page<OperationView>>(`/operations?request_key=${encodeURIComponent(requestKey)}`)
}

export function executeOperation(operation: OperationView, confirmed: boolean) {
  return request<OperationView>(`/operations/${encodeURIComponent(operation.id)}/executions`, {
    request_hash: operation.request_hash,
    confirmed,
  })
}
