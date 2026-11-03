export type Flag = 0 | 1
export type Mode = 'TAG' | 'ROAD'
export type Efficiency = 'HIGH' | 'MEDIUM' | 'LOW'

export interface Versioned {
  id: string
  version: string
  created_at: string
  updated_at: string
}

export interface Category extends Versioned {
  task_mode: Mode
  name: string
}

export interface Availability {
  work_date: string
  is_available: Flag
  unavailability_ids: string[]
  scheduled_shift_count: string
}

export interface Driver extends Versioned, Availability {
  name: string
  phone: string | null
  efficiency_level: Efficiency
  is_enabled: Flag
  can_morning: Flag
  can_middle: Flag
  can_evening: Flag
}

export const shifts = [
  { code: 'morning', label: '早班' },
  { code: 'middle', label: '中班' },
  { code: 'evening', label: '晚班' },
] as const

export const capacityFields = [
  'morning_max_tag_count', 'morning_max_road_meters',
  'middle_max_tag_count', 'middle_max_road_meters',
  'evening_max_tag_count', 'evening_max_road_meters',
] as const

export type CapacityField = typeof capacityFields[number]
export type Capacities = Record<CapacityField, string>

export interface Vehicle extends Versioned, Availability, Capacities {
  plate_number: string
  name: string | null
  notes: string | null
  is_enabled: Flag
}

export interface Unavailability extends Versioned {
  driver_id: string | null
  vehicle_id: string | null
  start_date: string
  end_date: string
  reason: string | null
}

export interface FieldChange {
  field: string
  label: string
  before: unknown
  after: unknown
}

export interface RelatedChange {
  plan_day_id: string | null
  work_date: string
  changes: FieldChange[]
}
