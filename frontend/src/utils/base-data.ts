import { ApiError } from '../api/client'

const maxInteger = 9223372036854775807n

export const labels: Record<string, string> = {
  name: '名称', task_mode: '采集模式', phone: '联系方式', efficiency_level: '效率等级',
  is_enabled: '启用状态', can_morning: '早班资格', can_middle: '中班资格', can_evening: '晚班资格',
  plate_number: '车牌号', notes: '备注', start_date: '开始日期', end_date: '结束日期', reason: '原因',
  driver_id: '司机编号', vehicle_id: '车辆编号', resource_unavailability: '关联不可用记录',
  morning_max_tag_count: '早班 Tag 容量（个）', middle_max_tag_count: '中班 Tag 容量（个）', evening_max_tag_count: '晚班 Tag 容量（个）',
  morning_max_road_meters: '早班道路容量（米）', middle_max_road_meters: '中班道路容量（米）', evening_max_road_meters: '晚班道路容量（米）',
  vehicle_capacities_json: '车辆容量基准', 'draft_metadata_json.needs_revalidation': '草稿待校验',
}

export const efficiencyLabels = { HIGH: '高', MEDIUM: '中', LOW: '低' } as const

export function uint(value: string): string {
  if (!/^(0|[1-9][0-9]*)$/.test(value) || BigInt(value) > maxInteger) {
    throw new Error('数量须为 0 至 9223372036854775807 的整数')
  }
  return value
}

export function kilometersToMeters(value: string): string {
  if (!/^(0|[1-9][0-9]*)(\.[0-9]{1,3})?$/.test(value)) {
    throw new Error('道路公里数须为非负数，最多三位小数')
  }
  const [whole, fraction = ''] = value.split('.')
  return uint((BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0'))).toString())
}

export function metersToKilometers(value: string): string {
  const meters = BigInt(value)
  const decimals = (meters % 1000n).toString().padStart(3, '0').replace(/0+$/, '')
  return `${meters / 1000n}${decimals ? `.${decimals}` : ''}`
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.response.errors.map(item => [item.work_date, item.field, item.message].filter(Boolean).join(' · '))
    return [error.message, ...details, `请求编号 ${error.response.request_id}`].join('\n')
  }
  return error instanceof Error ? error.message : '请求失败，请重试查询'
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  if (value === 'HIGH' || value === 'MEDIUM' || value === 'LOW') return efficiencyLabels[value]
  return String(value)
}
