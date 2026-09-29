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
