import { useEffect, useMemo, useState } from 'react'
import { getDataFiles, getResourceOptions } from '../api'
import type { ResourceAction, ResourceField } from '../types'

/**
 * Modal that collects an action's form values and confirms it.
 *
 * Shown for any action that declares fields or a confirm message. The three
 * field kinds that need more than an input box are handled here:
 *
 *   select with options_from  options come from another resource's cached
 *                             rows, so "move these DNs to partition X"
 *                             offers the partitions already synced from
 *                             that same cluster
 *   data_file                 the _DATA folder listing, same paths the
 *                             scripts use
 *   secret                    a password field; the value goes straight to
 *                             the API and is never rendered back or logged
 */

export interface ActionDialogProps {
  action: ResourceAction
  /** Row keys the action will run against; empty for a form action. */
  keys: string[]
  scope: string
  resourceLabel: string
  onCancel: () => void
  onConfirm: (params: Record<string, string>) => void
}

function initialValues(fields: readonly ResourceField[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of fields) out[f.name] = f.default ?? ''
  return out
}

export default function ActionDialog({
  action,
  keys,
  scope,
  resourceLabel,
  onCancel,
  onConfirm,
}: ActionDialogProps) {
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(action.fields))
  const [remoteOptions, setRemoteOptions] = useState<Record<string, string[]>>({})
  const [optionError, setOptionError] = useState<string | null>(null)

  // Pull the option lists for any select that borrows another resource's rows.
  useEffect(() => {
    let cancelled = false
    const sourced = action.fields.filter((f) => f.kind === 'select' && f.options_from)
    if (!sourced.length) return
    Promise.all(
      sourced.map((f) => {
        const [resourceId, fieldName = 'key'] = f.options_from.split(':')
        return getResourceOptions(resourceId, fieldName, scope)
          .then((res) => [f.name, res.options] as const)
          .catch(() => [f.name, [] as string[]] as const)
      }),
    ).then((pairs) => {
      if (cancelled) return
      const next: Record<string, string[]> = {}
      for (const [name, options] of pairs) next[name] = options
      setRemoteOptions(next)
      const empty = pairs.filter(([, options]) => options.length === 0).map(([name]) => name)
      if (empty.length) {
        setOptionError(
          'No cached values for: ' +
            empty.join(', ') +
            '. Sync that resource first, or type the value in.',
        )
      }
    })
    return () => {
      cancelled = true
    }
  }, [action, scope])

  const [dataFiles, setDataFiles] = useState<string[]>([])
  useEffect(() => {
    if (!action.fields.some((f) => f.kind === 'data_file')) return
    getDataFiles()
      .then((res) => setDataFiles(res.files.map((f) => f.path)))
      .catch(() => setDataFiles([]))
  }, [action])

  const missing = useMemo(
    () => action.fields.filter((f) => f.required && !(values[f.name] ?? '').trim()),
    [action.fields, values],
  )

  function set(name: string, value: string) {
    setValues((prev) => ({ ...prev, [name]: value }))
  }

  const targetSummary =
    action.scope_mode === 'selection'
      ? `${keys.length} ${resourceLabel.toLowerCase()} on ${scope}`
      : scope

  return (
    <div className="doc-modal-backdrop" onClick={onCancel}>
      <div className="action-dialog" onClick={(e) => e.stopPropagation()}>
        <h2>{action.label}</h2>
        <p className="action-dialog-target">{targetSummary}</p>

        {action.help && <p className="action-dialog-help">{action.help}</p>}

        {action.scope_mode === 'selection' && keys.length > 0 && (
          <div className="action-dialog-keys">
            {keys.slice(0, 12).map((k) => (
              <span key={k} className="pill pill-muted">
                {k}
              </span>
            ))}
            {keys.length > 12 && <span className="cell-muted">+{keys.length - 12} more</span>}
          </div>
        )}

        {action.fields.map((field) => {
          const options = field.options_from
            ? remoteOptions[field.name] ?? []
            : field.options
          const id = `action-field-${field.name}`
          return (
            <div key={field.name} className="option-field">
              <label htmlFor={id}>
                {field.label}
                {field.required && <span className="required-tag">required</span>}
              </label>

              {field.kind === 'bool' ? (
                <label className="checkbox-label">
                  <input
                    id={id}
                    type="checkbox"
                    checked={values[field.name] === 'true'}
                    onChange={(e) => set(field.name, e.target.checked ? 'true' : 'false')}
                  />
                  {field.placeholder || 'Enabled'}
                </label>
              ) : field.kind === 'select' || field.kind === 'data_file' ? (
                <>
                  <select
                    id={id}
                    value={values[field.name] ?? ''}
                    onChange={(e) => set(field.name, e.target.value)}
                  >
                    <option value="">{field.placeholder || 'Choose...'}</option>
                    {(field.kind === 'data_file' ? dataFiles : options).map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                  {field.kind === 'select' && (
                    <input
                      type="text"
                      placeholder="or type a value"
                      value={values[field.name] ?? ''}
                      onChange={(e) => set(field.name, e.target.value)}
                    />
                  )}
                </>
              ) : field.kind === 'textarea' ? (
                <textarea
                  id={id}
                  rows={4}
                  value={values[field.name] ?? ''}
                  placeholder={field.placeholder}
                  onChange={(e) => set(field.name, e.target.value)}
                />
              ) : (
                <input
                  id={id}
                  type={field.kind === 'secret' ? 'password' : field.kind === 'number' ? 'number' : 'text'}
                  autoComplete={field.kind === 'secret' ? 'new-password' : 'off'}
                  value={values[field.name] ?? ''}
                  placeholder={field.placeholder}
                  onChange={(e) => set(field.name, e.target.value)}
                />
              )}

              {field.help && <div className="field-hint">{field.help}</div>}
              {field.kind === 'secret' && (
                <div className="field-hint">
                  Sent straight to the server and never shown, stored or written to a log.
                </div>
              )}
            </div>
          )
        })}

        {optionError && <div className="field-hint field-hint-warn">{optionError}</div>}

        {action.confirm && <div className="action-dialog-confirm">{action.confirm}</div>}

        <div className="settings-edit-actions">
          <button
            className={`btn btn-${action.style === 'danger' ? 'danger' : 'primary'}`}
            disabled={missing.length > 0}
            onClick={() => onConfirm(values)}
          >
            {action.label}
          </button>
          <button className="btn btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          {missing.length > 0 && (
            <span className="cell-muted">
              Needs: {missing.map((f) => f.label).join(', ')}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
