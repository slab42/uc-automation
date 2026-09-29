import type {
  CredentialsResponse,
  DataFileInfo,
  DataFilesResponse,
  HealthResponse,
  InventoryResponse,
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
