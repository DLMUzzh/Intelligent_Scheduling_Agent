import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request, TransportError } from '../src/api/client'
import { executeOperation } from '../src/api/operations'
import type { OperationView } from '../src/types/api'

const response = { success: true, code: 'OK', message: '查询成功', data: { status: 'FAILED' },
  errors: [], request_id: 'test', data_revision: '1' }

afterEach(() => vi.unstubAllGlobals())

describe('统一请求封装', () => {
  it('保留查询到的业务失败状态', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(response))))
    const result = await request<{ status: string }>('/operations/1')
    expect(result.data?.status).toBe('FAILED')
  })

  it('保留失败响应中的操作记录及追踪信息', async () => {
    const failure = { ...response, success: false, code: 'VERSION_CONFLICT' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(failure), { status: 409 })))
    await expect(request('/operations/1/executions', {})).rejects.toMatchObject({
      status: 409, response: { code: 'VERSION_CONFLICT', request_id: 'test', data: { status: 'FAILED' } },
    })
    expect(new ApiError(failure, 409).message).toBe('查询成功')
  })

  it('传输失败不自动重试写操作', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('offline'))
    vi.stubGlobal('fetch', fetcher)
    await expect(request('/operations', {})).rejects.toMatchObject({ outcomeUnknown: true })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('读取连接失败可以与未知写结果区分', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    await expect(request('/context')).rejects.toBeInstanceOf(TransportError)
    await expect(request('/context')).rejects.toMatchObject({ outcomeUnknown: false })
  })

  it('执行请求仅包含冻结摘要 hash 与确认标记', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)))
    vi.stubGlobal('fetch', fetcher)
    await executeOperation({ id: '9007199254740993', request_hash: 'a'.repeat(64) } as OperationView, true)
    expect(fetcher).toHaveBeenCalledWith('/api/v1/operations/9007199254740993/executions', expect.objectContaining({
      body: JSON.stringify({ request_hash: 'a'.repeat(64), confirmed: true }), method: 'POST',
    }))
  })
})
