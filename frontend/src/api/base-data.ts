import { request } from './client'
import type { Page } from '../types/api'
import type { Category, Driver, Unavailability, Vehicle } from '../types/base-data'

export type Query = Record<string, string | number | undefined>

function queryString(query: Query) {
  const params = new URLSearchParams()
  for (const [field, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(field, String(value))
  }
  return params.size ? `?${params}` : ''
}

export function listCategories(query: Query = {}) {
  return request<Page<Category>>(`/collection-categories${queryString(query)}`)
}

export function listDrivers(query: Query = {}) {
  return request<Page<Driver>>(`/drivers${queryString(query)}`)
}

export function getDriver(id: string, workDate?: string) {
  return request<Driver>(`/drivers/${encodeURIComponent(id)}${queryString({ work_date: workDate })}`)
}

export function listVehicles(query: Query = {}) {
  return request<Page<Vehicle>>(`/vehicles${queryString(query)}`)
}

export function getVehicle(id: string, workDate?: string) {
  return request<Vehicle>(`/vehicles/${encodeURIComponent(id)}${queryString({ work_date: workDate })}`)
}

export function listUnavailability(query: Query = {}) {
  return request<Page<Unavailability>>(`/resource-unavailability${queryString(query)}`)
}

export function getUnavailability(id: string) {
  return request<Unavailability>(`/resource-unavailability/${encodeURIComponent(id)}`)
}
