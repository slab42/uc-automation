export interface ScriptOption {
  flags: string[]
  dest: string
  positional: boolean
  action: string | null
  help: string | null
  default: string | null
  choices: string[] | null
  required: boolean
  type: string | null
  nargs: string | null
  metavar: string | null
}

export interface ScriptInfo {
  rel: string
  filename: string
  title: string
  category: string
  takes_args: boolean
  description: string | null
  argparse?: boolean
  options?: ScriptOption[]
  /** Rich-GUI layout for this script's page; null = prompt runner only. */
  page?: PageSpec | null
}

export interface SkippedScript {
  rel: string
  reason: string
}

export interface CategoryInfo {
  label: string
  dir: string
  description: string
  scripts: ScriptInfo[]
}

export interface ScriptsResponse {
  categories: CategoryInfo[]
  skipped: SkippedScript[]
}

export interface HealthResponse {
  status: string
  root: string
  python: string
}

export interface CredentialSection {
  section: string
  service: string
  identifier: string
  fields: Record<string, string>
  secrets: Record<string, boolean>
}

export interface CredentialsResponse {
  path: string
  exists: boolean
  sections: CredentialSection[]
}

export type SecretAction =
  | { action: 'keep' }
  | { action: 'set'; value: string }
  | { action: 'clear' }

export interface UpdateSectionBody {
  fields: Record<string, string>
  secrets: Record<string, SecretAction>
}

export interface InventoryCluster {
  name: string
  server: string
  version: string
  cluster_type: string
  server_type: string
}

export interface InventoryRouter {
  name: string
  ip: string
}

export interface InventoryResponse {
  clusters: InventoryCluster[]
  routers: InventoryRouter[]
}

export interface DataFileInfo {
  name: string
  path: string
  size: number
  modified: string
}

export interface DataFilesResponse {
  dir: string
  files: DataFileInfo[]
}

export type PromptKind = 'text' | 'secret' | 'yes_no' | 'choice' | 'file' | 'continue'

export interface ChoiceOption {
  value: string
  label: string
}

export interface PromptMessage {
  type: 'prompt'
  id: number
  text: string
  label: string
  kind: PromptKind
  secret: boolean
  default: string
  choices: ChoiceOption[]
  suggestions: ChoiceOption[]
  allow_other: boolean
}

export type WsClientMessage =
  | { type: 'answer'; id: number; value: string }
  | { type: 'kill' }

export type WsServerMessage =
  | { type: 'started'; pid: number; command: string[] }
  | { type: 'output'; data: string }
  | PromptMessage
  | { type: 'exit'; code: number }
  | { type: 'error'; message: string }

// -- rich resource pages ---------------------------------------------------
// Mirrors gui/backend/resources/types.py. A resource page is rendered
// entirely from the ResourceSpec the API returns, so adding a resource on
// the backend needs no change here.

export type ColumnKind =
  | 'text'
  | 'number'
  | 'bool'
  | 'badge'
  | 'deps'
  | 'list'
  | 'bytes'
  | 'date'

export interface ResourceColumn {
  key: string
  label: string
  kind: ColumnKind
  width: string | null
  tone_map: Record<string, string>
  optional: boolean
  help: string
}

export type FieldKind = 'text' | 'number' | 'select' | 'bool' | 'textarea' | 'secret' | 'data_file'

export interface ResourceField {
  name: string
  label: string
  kind: FieldKind
  default: string
  required: boolean
  options: string[]
  placeholder: string
  help: string
  options_from: string
}

export type ScopeMode = 'selection' | 'form' | 'none'

export interface ResourceAction {
  id: string
  label: string
  scope_mode: ScopeMode
  style: 'primary' | 'secondary' | 'danger'
  confirm: string
  block_when_deps: boolean
  removes_row: boolean
  fields: ResourceField[]
  help: string
}

export interface SyncStateRow {
  resource: string
  scope: string
  synced_at: string
  item_count: number
  duration_ms: number | null
  status: string
  message: string | null
}

export interface ResourceSpec {
  id: string
  service: string
  label: string
  key_label: string
  description: string
  columns: ResourceColumn[]
  has_deps: boolean
  deps_label: string
  deps_expensive: boolean
  actions: ResourceAction[]
  filters: ResourceField[]
  protected_keys: string[]
  sync_note: string
  docs_url: string
  cached_items: number
  sync_state: SyncStateRow[]
  last_sync: string | null
}

export interface ConnectionTarget {
  service: string
  name: string
  server: string
  version: string
  server_type?: string
  section: string | null
  username: string
  secret_key: string
  has_stored_secret: boolean
  unlocked: boolean
  ready: boolean
}

export interface ResourceDetail extends ResourceSpec {
  targets: ConnectionTarget[]
}

export interface ResourceDependency {
  name: string
  type: string
  detail: string
}

export interface ResourceItem {
  key: string
  scope: string
  fields: Record<string, string | number | boolean | null>
  deps: ResourceDependency[] | null
  deps_count: number | null
  synced_at: string
}

export interface ResourceItemsResponse {
  resource: string
  scopes: string[]
  columns: ResourceColumn[]
  key_label: string
  protected_keys: string[]
  items: ResourceItem[]
  sync_state: SyncStateRow[]
}

export interface ResourceCatalogService {
  service: string
  targets: ConnectionTarget[]
  resources: ResourceSpec[]
}

export interface ResourceCatalog {
  services: ResourceCatalogService[]
}

export interface ActionResultRow {
  key: string
  success: boolean
  message: string
}

export interface JobStatus {
  id: string
  kind: 'sync' | 'action' | 'deps' | 'sync_all'
  label: string
  meta: Record<string, unknown>
  status: 'running' | 'done' | 'error' | 'cancelled'
  done: number
  total: number | null
  message: string
  log: string[]
  log_total: number
  result: {
    succeeded?: number
    failed?: number
    results?: ActionResultRow[]
    outcomes?: Array<Record<string, unknown>>
    item_count?: number
    pairs?: number
    [k: string]: unknown
  } | null
  error: string | null
  started_at: string
  finished_at: string | null
  version: number
}

export interface JobHandle {
  job_id: string
  label: string
  pairs?: number
}

export interface NeedsCredentials {
  code: 'needs_credentials'
  service?: string
  name?: string
  username?: string
  message: string
}

export interface DbStats {
  path: string
  size_bytes: number
  item_count: number
  resource_count: number
  scope_count: number
  last_sync: string | null
}

export interface DbResourceRow {
  id: string
  service: string
  label: string
  cached_items: number
  has_deps: boolean
  sync_state: SyncStateRow[]
}

export interface DbOverview {
  stats: DbStats
  resources: DbResourceRow[]
  orphan_resources: string[]
}

export interface ActionLogRow {
  id: number
  at: string
  resource: string | null
  scope: string | null
  action: string | null
  item_key: string | null
  success: boolean
  message: string | null
}

export interface ConnectionsResponse {
  services: Array<{ service: string; targets: ConnectionTarget[] }>
  wsdl_versions: string[]
}

export interface PageSpec {
  resources: string[]
  intro: string
  hide_actions: string[]
  deps_default: boolean
  filters: Record<string, string>
}
