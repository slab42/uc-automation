import type {
  ActionLogRow,
  ConnectionsResponse,
  CredentialsResponse,
  DataFileInfo,
  DataFilesResponse,
  DbOverview,
  HealthResponse,
  InventoryResponse,
  JobHandle,
  JobStatus,
  ResourceCatalog,
  ResourceDetail,
  ResourceItemsResponse,
  ScriptInfo,
  ScriptsResponse,
  UpdateSectionBody,
} from './types'

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      // ignore
    }
    throw new Error(detail || `Request failed: ${res.status}`)
  }
  if (res.status === 204) {
    return undefined as unknown as T
  }
  return (await res.json()) as T
}

export function getHealth(): Promise<HealthResponse> {
  return jsonFetch('/api/health')
}

export function getScripts(): Promise<ScriptsResponse> {
  return jsonFetch('/api/scripts')
}

export function getScript(rel: string): Promise<ScriptInfo> {
  return jsonFetch(`/api/scripts/${rel}`)
}

export function getCredentials(): Promise<CredentialsResponse> {
  return jsonFetch('/api/credentials')
}

export function putCredentialSection(section: string, body: UpdateSectionBody) {
  return jsonFetch(`/api/credentials/${encodeURIComponent(section)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function deleteCredentialSection(section: string): Promise<void> {
  return jsonFetch(`/api/credentials/${encodeURIComponent(section)}`, {
    method: 'DELETE',
  })
}

export function getInventory(): Promise<InventoryResponse> {
  return jsonFetch('/api/inventory')
}

export function buildWsUrl(rel: string, args: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const params = new URLSearchParams({ args })
  return `${proto}//${location.host}/ws/run/${rel}?${params.toString()}`
}

export function getDataFiles(): Promise<DataFilesResponse> {
  return jsonFetch('/api/data-files')
}

export function getDataFileDownloadUrl(name: string): string {
  return `/api/data-files/${encodeURIComponent(name)}`
}

export async function uploadDataFile(file: File, overwrite = false): Promise<DataFileInfo> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`/api/data-files?overwrite=${overwrite ? 'true' : 'false'}`, {
    method: 'POST',
    body: form,
  })
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}))
    const err = new Error(body.detail || 'File already exists') as Error & { conflict?: boolean }
    err.conflict = true
    throw err
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      // ignore
    }
    throw new Error(detail || `Upload failed: ${res.status}`)
  }
  return (await res.json()) as DataFileInfo
}

// -- rich resource pages ---------------------------------------------------

/** A 409 from the API means a target has no usable password yet. */
export class NeedsCredentialsError extends Error {
  service: string
  /** The target that needs unlocking; `name` is taken by Error itself. */
  target: string
  username: string

  constructor(detail: { message?: string; service?: string; name?: string; username?: string }) {
    super(detail.message || 'Credentials required')
    this.name = 'NeedsCredentialsError'
    this.service = detail.service || ''
    this.target = detail.name || ''
    this.username = detail.username || ''
  }
}

/** jsonFetch, but a needs_credentials 409 becomes NeedsCredentialsError. */
async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}))
    const detail = body?.detail
    if (detail && typeof detail === 'object' && detail.code === 'needs_credentials') {
      throw new NeedsCredentialsError(detail)
    }
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (typeof body?.detail?.message === 'string') detail = body.detail.message
    } catch {
      // ignore
    }
    throw new Error(detail || `Request failed: ${res.status}`)
  }
  if (res.status === 204) return undefined as unknown as T
  return (await res.json()) as T
}

const postJson = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body ?? {}),
})

export function getResourceCatalog(): Promise<ResourceCatalog> {
  return apiFetch('/api/resources')
}

export function getResource(id: string): Promise<ResourceDetail> {
  return apiFetch(`/api/resources/${encodeURIComponent(id)}`)
}

export function getResourceItems(id: string, scope?: string): Promise<ResourceItemsResponse> {
  const q = scope ? `?scope=${encodeURIComponent(scope)}` : ''
  return apiFetch(`/api/resources/${encodeURIComponent(id)}/items${q}`)
}

export function getResourceExportUrl(id: string, scope?: string): string {
  const q = scope ? `?scope=${encodeURIComponent(scope)}` : ''
  return `/api/resources/${encodeURIComponent(id)}/export.csv${q}`
}

export function getResourceOptions(
  id: string,
  field: string,
  scope?: string,
): Promise<{ options: string[] }> {
  const params = new URLSearchParams({ field })
  if (scope) params.set('scope', scope)
  return apiFetch(`/api/resources/${encodeURIComponent(id)}/options?${params.toString()}`)
}

export function syncResource(
  id: string,
  body: { scopes?: string[]; include_deps?: boolean; params?: Record<string, string> },
): Promise<JobHandle> {
  return apiFetch(`/api/resources/${encodeURIComponent(id)}/sync`, postJson(body))
}

export function scanResourceDeps(
  id: string,
  body: { scope: string; keys: string[] },
): Promise<JobHandle> {
  return apiFetch(`/api/resources/${encodeURIComponent(id)}/deps`, postJson(body))
}

export function runResourceAction(
  id: string,
  actionId: string,
  body: { scope: string; keys: string[]; params: Record<string, string> },
): Promise<JobHandle> {
  return apiFetch(
    `/api/resources/${encodeURIComponent(id)}/actions/${encodeURIComponent(actionId)}`,
    postJson(body),
  )
}

export function getJob(jobId: string, logFrom = 0): Promise<JobStatus> {
  return apiFetch(`/api/jobs/${jobId}?log_from=${logFrom}`)
}

export function cancelJob(jobId: string): Promise<JobStatus> {
  return apiFetch(`/api/jobs/${jobId}/cancel`, postJson({}))
}

export function buildJobWsUrl(jobId: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/jobs/${jobId}`
}

export function getConnections(): Promise<ConnectionsResponse> {
  return apiFetch('/api/connections')
}

/** Send a password for this server process to hold in memory only. */
export function unlockConnection(
  service: string,
  name: string,
  secret: string,
  username?: string,
): Promise<unknown> {
  return apiFetch(
    `/api/connections/${encodeURIComponent(service)}/${encodeURIComponent(name)}/unlock`,
    postJson({ secret, username: username || '' }),
  )
}

export function forgetConnections(service?: string, name?: string): Promise<{ forgotten: number }> {
  return apiFetch('/api/connections/forget', postJson({ service, name }))
}

export function getDbOverview(): Promise<DbOverview> {
  return apiFetch('/api/db')
}

export function getDbActions(limit = 100): Promise<{ actions: ActionLogRow[] }> {
  return apiFetch(`/api/db/actions?limit=${limit}`)
}

export function syncWholeDb(body: {
  include_deps?: boolean
  resources?: string[]
}): Promise<JobHandle> {
  return apiFetch('/api/db/sync-all', postJson(body))
}

export function clearDb(resource?: string, scope?: string): Promise<{ removed: number }> {
  const params = new URLSearchParams()
  if (resource) params.set('resource', resource)
  if (scope) params.set('scope', scope)
  const q = params.toString()
  return apiFetch(`/api/db${q ? `?${q}` : ''}`, { method: 'DELETE' })
}
