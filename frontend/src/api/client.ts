import type { ApiEnvelope } from '../types/api'

export class ApiError<T = unknown> extends Error {
  constructor(readonly response: ApiEnvelope<T>, readonly status: number) {
    super(response.message)
  }
}

export class TransportError extends Error {
  constructor(readonly outcomeUnknown: boolean) {
    super(outcomeUnknown
      ? '连接中断，操作结果待核实，请通过原操作编号查询。'
      : '无法连接本机服务，请检查运行状态后刷新。')
  }
}

export async function request<T>(path: string, body?: object): Promise<ApiEnvelope<T>> {
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    })
  } catch {
    throw new TransportError(body !== undefined)
  }
  let envelope: ApiEnvelope<T>
  try {
    envelope = await response.json() as ApiEnvelope<T>
  } catch {
    throw new TransportError(body !== undefined)
  }
  if (!response.ok || !envelope.success) {
    throw new ApiError(envelope, response.status)
  }
  return envelope
}
