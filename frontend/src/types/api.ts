export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }

export interface ErrorItem {
  code: string
  message: string
  field: string | null
  target_type: string | null
  target_id: string | null
  work_date: string | null
}

export interface ApiEnvelope<T> {
  success: boolean
  code: string
  message: string
  data: T | null
  errors: ErrorItem[]
  request_id: string
  data_revision: string | null
}

export interface LocalContext {
  actor_code: 'LOCAL_CAPTAIN'
  actor_name: string
  business_date: string
  timezone: 'Asia/Shanghai'
  notification_status: 'NOT_CONNECTED'
}

export interface ObjectVersion {
  id: string
  version: string
}

export interface ExpectedVersions {
  business_revision: string
  collection_plans?: ObjectVersion[]
  plan_days?: (ObjectVersion & { formal_version: string })[]
  collection_categories?: ObjectVersion[]
  drivers?: ObjectVersion[]
  vehicles?: ObjectVersion[]
  resource_unavailability?: ObjectVersion[]
}

export interface PrepareInput {
  request_key: string
  action_code: string
  target_type: string
  target_id: string | null
  payload: Record<string, JsonValue>
  expected_versions_json: ExpectedVersions
}

export interface OperationView {
  id: string
  request_key: string
  request_hash: string
  action_code: string
  entry_source: 'PAGE' | 'AGENT'
  target_type: string
  target_id: string | null
  requires_confirmation: 0 | 1
  status: 'PENDING' | 'SUCCEEDED' | 'FAILED'
  confirmed_at: string | null
  result_code: string | null
  result_json: Record<string, JsonValue> | null
  error_message: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  summary_json: Record<string, JsonValue>
  expected_versions_json: ExpectedVersions
}

export interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: string
}
