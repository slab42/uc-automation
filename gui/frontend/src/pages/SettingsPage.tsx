import { useEffect, useMemo, useRef, useState } from 'react'
import {
  deleteCredentialSection,
  getCredentials,
  getDataFileDownloadUrl,
  getDataFiles,
  getInventory,
  putCredentialSection,
  uploadDataFile,
} from '../api'
import type {
  CredentialSection,
  CredentialsResponse,
  DataFilesResponse,
  InventoryResponse,
  SecretAction,
} from '../types'

function formatSize(bytes: number): string {
  const kb = bytes / 1024
  return `${kb.toFixed(kb < 10 ? 2 : 0)} KB`
}

function formatModified(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

const SERVICES = ['CUCM', 'CUC', 'CUBE', 'WEBEX'] as const

interface EditFormState {
  username: string
  secretValues: Record<string, string>
  secretClear: Record<string, boolean>
}

function emptyEditForm(section: CredentialSection): EditFormState {
  const secretValues: Record<string, string> = {}
  const secretClear: Record<string, boolean> = {}
  for (const key of Object.keys(section.secrets)) {
    secretValues[key] = ''
    secretClear[key] = false
  }
  return { username: section.fields.username ?? '', secretValues, secretClear }
}

export default function SettingsPage() {
  const [creds, setCreds] = useState<CredentialsResponse | null>(null)
  const [inventory, setInventory] = useState<InventoryResponse | null>(null)
  const [dataFiles, setDataFiles] = useState<DataFilesResponse | null>(null)
  const [dataFilesError, setDataFilesError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [editingSection, setEditingSection] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<EditFormState | null>(null)
  const [saving, setSaving] = useState(false)
  const [showAddForm, setShowAddForm] = useState(false)

  const [addService, setAddService] = useState<(typeof SERVICES)[number]>('CUCM')
  const [addIdentifier, setAddIdentifier] = useState('')
  const [addUsername, setAddUsername] = useState('')
  const [addSecret, setAddSecret] = useState('')

  function reload() {
    getCredentials()
      .then(setCreds)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
    getInventory()
      .then(setInventory)
      .catch(() => {
        /* inventory is optional for suggestions */
      })
  }

  function reloadDataFiles() {
    getDataFiles()
      .then(setDataFiles)
      .catch((err) => setDataFilesError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    reload()
    reloadDataFiles()
  }, [])

  async function handleUploadDataFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setDataFilesError(null)
    setUploading(true)
    try {
      try {
        await uploadDataFile(file, false)
      } catch (err) {
        const conflict = (err as Error & { conflict?: boolean }).conflict
        if (conflict && confirm(`A file named "${file.name}" already exists. Overwrite it?`)) {
          await uploadDataFile(file, true)
        } else {
          throw err
        }
      }
      reloadDataFiles()
    } catch (err) {
      setDataFilesError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const sectionsByService = useMemo(() => {
    const map = new Map<string, CredentialSection[]>()
    for (const svc of SERVICES) map.set(svc, [])
    for (const s of creds?.sections ?? []) {
      const list = map.get(s.service)
      if (list) list.push(s)
      else map.set(s.service, [s])
    }
    return map
  }, [creds])

  const identifierSuggestions = useMemo(() => {
    const set = new Set<string>(['default'])
    if (inventory) {
      if (addService === 'CUCM' || addService === 'CUC') {
        for (const c of inventory.clusters) set.add(c.name)
      }
      if (addService === 'CUBE') {
        for (const r of inventory.routers) set.add(r.name)
      }
    }
    return Array.from(set)
  }, [inventory, addService])

  function startEdit(section: CredentialSection) {
    setEditingSection(section.section)
    setEditForm(emptyEditForm(section))
  }

  function cancelEdit() {
    setEditingSection(null)
    setEditForm(null)
  }

  async function saveEdit(section: CredentialSection) {
    if (!editForm) return
    setSaving(true)
    setError(null)
    try {
      const secrets: Record<string, SecretAction> = {}
      for (const key of Object.keys(section.secrets)) {
        const value = editForm.secretValues[key] ?? ''
        if (value.length > 0) {
          secrets[key] = { action: 'set', value }
        } else if (editForm.secretClear[key]) {
          secrets[key] = { action: 'clear' }
        } else {
          secrets[key] = { action: 'keep' }
        }
      }
      await putCredentialSection(section.section, {
        fields: { ...section.fields, username: editForm.username },
        secrets,
      })
      cancelEdit()
      reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(section: CredentialSection) {
    if (!confirm(`Delete credentials section "${section.section}"? This cannot be undone.`)) {
      return
    }
    setError(null)
    try {
      await deleteCredentialSection(section.section)
      reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleAdd() {
    if (!addIdentifier.trim()) {
      setError('Identifier is required')
      return
    }
    const section = `${addService}:${addIdentifier.trim()}`
    const secretKey = addService === 'WEBEX' ? 'api_token' : 'password'
    setSaving(true)
    setError(null)
    try {
      await putCredentialSection(section, {
        fields: { username: addUsername },
        secrets: {
          [secretKey]: addSecret ? { action: 'set', value: addSecret } : { action: 'clear' },
        },
      })
      setShowAddForm(false)
      setAddIdentifier('')
      setAddUsername('')
      setAddSecret('')
      reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page settings-page">
      <h1>Settings</h1>
      <p className="settings-note">
        Passwords are written to <code>.env/credentials.env</code>, which is not checked in.
        Leave a password blank to be prompted at runtime (recommended).
      </p>

      {creds && (
        <p className="settings-path">
          File: <code>{creds.path}</code>: {creds.exists ? 'exists' : 'does not exist yet'}
        </p>
      )}

      {error && <div className="error-banner">{error}</div>}

      <div className="settings-cards">
        {SERVICES.map((svc) => (
          <div key={svc} className="settings-card">
            <h2>{svc}</h2>
            {(sectionsByService.get(svc) ?? []).length === 0 && (
              <p className="settings-empty">No sections configured.</p>
            )}
            {(sectionsByService.get(svc) ?? []).map((section) => (
              <div key={section.section} className="settings-row">
                <div className="settings-row-main">
                  <span className="settings-identifier">{section.identifier}</span>
                  {Object.entries(section.fields).map(([k, v]) => (
                    <span key={k} className="settings-field">
                      {k}: {v}
                    </span>
                  ))}
                  {Object.entries(section.secrets).map(([key, isSet]) => (
                    <span
                      key={key}
                      className={`pill ${isSet ? 'pill-set' : 'pill-blank'}`}
                    >
                      {key}: {isSet ? 'set' : 'blank (prompts at runtime)'}
                    </span>
                  ))}
                </div>
                <div className="settings-row-actions">
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => startEdit(section)}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => handleDelete(section)}
                  >
                    Delete
                  </button>
                </div>

                {editingSection === section.section && editForm && (
                  <div className="settings-edit-form">
                    <label>
                      Username
                      <input
                        type="text"
                        value={editForm.username}
                        onChange={(e) =>
                          setEditForm({ ...editForm, username: e.target.value })
                        }
                      />
                    </label>
                    {Object.keys(section.secrets).map((key) => (
                      <div key={key} className="settings-secret-field">
                        <label>
                          {key}
                          <input
                            type="password"
                            placeholder="leave blank to keep current"
                            value={editForm.secretValues[key] ?? ''}
                            onChange={(e) =>
                              setEditForm({
                                ...editForm,
                                secretValues: {
                                  ...editForm.secretValues,
                                  [key]: e.target.value,
                                },
                              })
                            }
                          />
                        </label>
                        <label className="checkbox-label">
                          <input
                            type="checkbox"
                            checked={editForm.secretClear[key] ?? false}
                            onChange={(e) =>
                              setEditForm({
                                ...editForm,
                                secretClear: {
                                  ...editForm.secretClear,
                                  [key]: e.target.checked,
                                },
                              })
                            }
                          />
                          Clear stored password
                        </label>
                      </div>
                    ))}
                    <div className="settings-edit-actions">
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => saveEdit(section)}
                        disabled={saving}
                      >
                        Save
                      </button>
                      <button className="btn btn-secondary btn-sm" onClick={cancelEdit}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="settings-add-section">
        {!showAddForm ? (
          <button className="btn btn-primary" onClick={() => setShowAddForm(true)}>
            Add section
          </button>
        ) : (
          <div className="settings-add-form">
            <h3>Add section</h3>
            <label>
              Service
              <select
                value={addService}
                onChange={(e) => setAddService(e.target.value as (typeof SERVICES)[number])}
              >
                {SERVICES.map((svc) => (
                  <option key={svc} value={svc}>
                    {svc}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Identifier
              <input
                type="text"
                list="identifier-suggestions"
                value={addIdentifier}
                onChange={(e) => setAddIdentifier(e.target.value)}
                placeholder="default"
              />
              <datalist id="identifier-suggestions">
                {identifierSuggestions.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </label>
            <label>
              Username
              <input
                type="text"
                value={addUsername}
                onChange={(e) => setAddUsername(e.target.value)}
              />
            </label>
            <label>
              {addService === 'WEBEX' ? 'API token' : 'Password'}
              <input
                type="password"
                value={addSecret}
                onChange={(e) => setAddSecret(e.target.value)}
                placeholder="leave blank to prompt at runtime"
              />
            </label>
            <div className="settings-edit-actions">
              <button className="btn btn-primary btn-sm" onClick={handleAdd} disabled={saving}>
                Save
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setShowAddForm(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="data-files-card">
        <h2>Data files</h2>
        <p className="data-files-hint">
          CSV and other input files used by scripts, stored in the <code>_DATA</code> folder.
        </p>

        {dataFilesError && <div className="error-banner">{dataFilesError}</div>}

        {dataFiles && dataFiles.files.length === 0 && (
          <p className="settings-empty">No data files found.</p>
        )}

        {dataFiles && dataFiles.files.length > 0 && (
          <table className="data-files-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Size</th>
                <th>Modified</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {dataFiles.files.map((f) => (
                <tr key={f.name}>
                  <td>{f.name}</td>
                  <td>{formatSize(f.size)}</td>
                  <td>{formatModified(f.modified)}</td>
                  <td>
                    <a href={getDataFileDownloadUrl(f.name)} download>
                      Download
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="data-files-upload">
          <label className="btn btn-secondary btn-sm upload-btn">
            {uploading ? 'Uploading...' : 'Upload data file'}
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.txt,.xlsx"
              onChange={handleUploadDataFile}
              disabled={uploading}
              style={{ display: 'none' }}
            />
          </label>
        </div>
      </div>
    </div>
  )
}
