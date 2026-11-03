import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { kilometersToMeters, metersToKilometers, uint } from '../src/utils/base-data'
import { useOperation } from '../src/stores/operation'
import type { OperationView, PrepareInput } from '../src/types/api'

const input: PrepareInput = { request_key: 'deebd050-8bd4-4b21-afda-f8c7a995f012', action_code: 'CREATE_DRIVER',
  target_type: 'DRIVER', target_id: null, payload: { name: '测试司机' }, expected_versions_json: { business_revision: '1' } }
const pending: OperationView = { id: '9007199254740993', request_key: input.request_key, request_hash: 'a'.repeat(64),
  action_code: input.action_code, entry_source: 'PAGE', target_type: 'DRIVER', target_id: null,
  requires_confirmation: 1, status: 'PENDING', confirmed_at: null, result_code: null, result_json: null,
  error_message: null, finished_at: null, created_at: '', updated_at: '', summary_json: {}, expected_versions_json: input.expected_versions_json }

function reply(data: unknown, status = 200, code = 'OK') {
  return new Response(JSON.stringify({ success: status < 300, code, message: '测试响应', data, errors: [], request_id: 'test', data_revision: '1' }), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
  const values = new Map<string, string>()
  vi.stubGlobal('sessionStorage', { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) })
})
afterEach(() => vi.unstubAllGlobals())

describe('精确容量转换', () => {
  it.each([['0', '0'], ['0.001', '1'], ['1.230', '1230'], ['9223372036854775.807', '9223372036854775807']])('公里 %s 精确转换到米', (kilometers, meters) => {
    expect(kilometersToMeters(kilometers)).toBe(meters)
  })
  it.each(['-1', '0.0001', '01', '1e3', 'Infinity', 'NaN', '9223372036854775.808'])('拒绝非法公里数 %s', value => {
    expect(() => kilometersToMeters(value)).toThrow()
  })
  it('大整数保持精度', () => {
    expect(uint('9007199254740993')).toBe('9007199254740993')
    expect(metersToKilometers('9223372036854775807')).toBe('9223372036854775.807')
    expect(metersToKilometers('1000')).toBe('1')
  })
})

describe('资料确认与未知结果', () => {
  it('准备只展示摘要，明确确认后才执行', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply(pending, 201)).mockResolvedValueOnce(reply({ ...pending, status: 'SUCCEEDED', target_id: '7' }))
    vi.stubGlobal('fetch', fetcher)
    const store = useOperation()
    await store.prepare(input)
    expect(store.operation?.status).toBe('PENDING')
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(store.completed).toBe(0)
    await store.confirm()
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(store.completed).toBe(1)
    expect(store.locked).toBe(false)
  })

  it('准备响应丢失保留原键，阻止换键写入并按键查询', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('connection lost'))
      .mockResolvedValueOnce(reply({ items: [pending], page: 1, page_size: 1, total: '1' }))
    vi.stubGlobal('fetch', fetcher)
    const store = useOperation()
    await store.prepare(input)
    expect(store.uncertain).toBe(true)
    await store.prepare({ ...input, request_key: 'other-key' })
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(store.input?.request_key).toBe(input.request_key)
    await store.verify()
    expect(store.operation?.id).toBe(pending.id)
    expect(store.uncertain).toBe(false)
    expect(fetcher.mock.calls[1][0]).toContain(input.request_key)
  })

  it('执行响应丢失后查询已成功结果，业务请求保持一次', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply(pending, 201)).mockRejectedValueOnce(new Error('lost'))
      .mockResolvedValueOnce(reply({ ...pending, status: 'SUCCEEDED' }))
    vi.stubGlobal('fetch', fetcher)
    const store = useOperation()
    await store.prepare(input)
    await store.confirm()
    expect(store.uncertain).toBe(true)
    await store.verify()
    expect(store.completed).toBe(1)
    expect(fetcher.mock.calls.filter(call => String(call[0]).includes('/executions'))).toHaveLength(1)
  })

  it('刷新浏览器后用同一请求键恢复待确认操作', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply(pending, 201))
      .mockResolvedValueOnce(reply({ items: [pending], page: 1, page_size: 1, total: '1' }))
    vi.stubGlobal('fetch', fetcher)
    await useOperation().prepare(input)
    setActivePinia(createPinia())
    const restored = useOperation()
    await restored.restore()
    expect(restored.operation?.request_key).toBe(input.request_key)
    expect(restored.operation?.status).toBe('PENDING')
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('失败终态显示真实状态并允许重新编辑', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(reply(pending, 201)).mockResolvedValueOnce(reply({ ...pending, status: 'FAILED', error_message: '版本冲突' }, 409, 'VERSION_CONFLICT')))
    const store = useOperation()
    await store.prepare(input)
    await store.confirm()
    expect(store.operation?.status).toBe('FAILED')
    expect(store.completed).toBe(0)
    expect(store.uncertain).toBe(false)
    expect(store.locked).toBe(false)
  })

  it('未知执行查到 PENDING 时持续绑定原操作，阻止关闭后换键重写', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply(pending, 201)).mockRejectedValueOnce(new Error('lost'))
      .mockResolvedValueOnce(reply(pending)).mockResolvedValueOnce(reply({ ...pending, status: 'SUCCEEDED' }))
    vi.stubGlobal('fetch', fetcher)
    const store = useOperation()
    await store.prepare(input)
    await store.confirm()
    await store.verify()
    expect(store.uncertain).toBe(false)
    expect(store.canClose).toBe(false)
    store.close()
    expect(store.operation?.id).toBe(pending.id)
    await store.prepare({ ...input, request_key: 'new-key' })
    expect(fetcher).toHaveBeenCalledTimes(3)
    await store.confirm()
    expect(store.operation?.status).toBe('SUCCEEDED')
    expect(fetcher.mock.calls[1][0]).toBe(fetcher.mock.calls[3][0])
    expect(store.canClose).toBe(true)
  })
})
