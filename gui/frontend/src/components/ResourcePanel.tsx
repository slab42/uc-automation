import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  NeedsCredentialsError,
  getResource,
  getResourceExportUrl,
  getResourceItems,
  runResourceAction,
  scanResourceDeps,
  syncResource,
} from '../api'
import { useJob } from '../hooks/useJob'
import type {
  ConnectionTarget,
  JobStatus,
  ResourceAction,
  ResourceDetail,
  ResourceItem,
} from '../types'
import ActionDialog from './ActionDialog'
import JobPanel from './JobPanel'
import ResourceTable from './ResourceTable'
import UnlockDialog from './UnlockDialog'

/**
 * One resource, end to end: pick a system, Sync, tick rows, press a button.
 *
 * This component is the whole rich-GUI story, and it is generic. Everything
 * it draws comes from the ResourceSpec the API returns, so a script page is
 * just a list of resource ids (see gui/backend/pages.py) and the Database
 * page reuses the same panel.
 *
 * Three behaviours worth knowing:
 *
 * - The table is fed from the local SQLite cache, never from a live call,
 *   so the panel opens instantly and still works with the cluster down.
 *   Only Sync goes out to the network.
 * - A dependency scan costs several queries per row, so it is opt-in:
 *   either tick "include dependencies" before a sync, or tick some rows and
 *   press Check dependencies.
 * - Actions that can strand configuration are gated. An action declared
 *   with block_when_deps refuses any row the cache shows as in use, which
 *   is how "delete the unused softkey templates" stays safe without the
 *   operator having to read the table carefully.
 */

export interface ResourcePanelProps {
  resourceId: string
  /** Action ids this page does not want (see pages.py hide_actions). */
  hideActions?: string[]
  depsDefault?: boolean
  initialFilters?: Record<string, string>
  /** Collapse the panel behind its heading; used for a page's second panel. */
  startCollapsed?: boolean
}

export default function ResourcePanel({
  resourceId,
  hideActions = [],
  depsDefault = false,
  initialFilters = {},
  startCollapsed = false,
}: ResourcePanelProps) {
  const [spec, setSpec] = useState<ResourceDetail | null>(null)
  const [items, setItems] = useState<ResourceItem[]>([])
  const [scope, setScope] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [includeDeps, setIncludeDeps] = useState(depsDefault)
  const [filters, setFilters] = useState<Record<string, string>>(initialFilters)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [collapsed, setCollapsed] = useState(startCollapsed)
  const [pendingAction, setPendingAction] = useState<ResourceAction | null>(null)
  const [unlockFor, setUnlockFor] = useState<{ name: string; message: string } | null>(null)

  const loadItems = useCallback(
    (forScope: string) =>
      getResourceItems(resourceId, forScope || undefined)
        .then((res) => {
          setItems(res.items)
          setError(null)
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err))),
    [resourceId],
  )

  const reload = useCallback(
    (keepScope?: string) =>
      getResource(resourceId)
        .then((res) => {
          setSpec(res)
          const preferred =
            keepScope ||
            res.targets.find((t) => t.ready)?.name ||
            res.targets[0]?.name ||
            ''
          setScope((prev) => prev || preferred)
          return loadItems(keepScope || preferred)
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)))
        .finally(() => setLoading(false)),
    [resourceId, loadItems],
  )

  useEffect(() => {
    setLoading(true)
    reload()
  }, [reload])

  const onJobFinish = useCallback(
    (finished: JobStatus) => {
      // Rows may have been added, removed or re-scanned; the cache is the
      // source of truth, so just read it again.
      loadItems(scope)
      if (finished.kind === 'action') setSelected(new Set())
      getResource(resourceId).then(setSpec).catch(() => undefined)
    },
    [loadItems, scope, resourceId],
  )

  const { job, log, running, watch, stop, clear } = useJob(onJobFinish)

  const target: ConnectionTarget | null = useMemo(
    () => spec?.targets.find((t) => t.name === scope) ?? null,
    [spec, scope],
  )

  const visibleActions = useMemo(
    () => (spec?.actions ?? []).filter((a) => !hideActions.includes(a.id)),
    [spec, hideActions],
  )

  function handleApiError(err: unknown) {
    if (err instanceof NeedsCredentialsError) {
      setUnlockFor({ name: err.target || scope, message: err.message })
      return
    }
    setError(err instanceof Error ? err.message : String(err))
  }

  function changeScope(next: string) {
    setScope(next)
    setSelected(new Set())
    clear()
    loadItems(next)
  }

  function handleSync() {
    if (!scope) {
      setError('Choose a system first.')
      return
    }
    if (target && !target.ready) {
      setUnlockFor({ name: scope, message: `${spec?.service} ${scope} has no password yet.` })
      return
    }
    setError(null)
    syncResource(resourceId, { scopes: [scope], include_deps: includeDeps, params: filters })
      .then((handle) => watch(handle.job_id))
      .catch(handleApiError)
  }

  function handleScanDeps() {
    setError(null)
    scanResourceDeps(resourceId, { scope, keys: [...selected] })
      .then((handle) => watch(handle.job_id))
      .catch(handleApiError)
  }

  function startAction(action: ResourceAction) {
    if (action.fields.length > 0 || action.confirm) {
      setPendingAction(action)
      return
    }
    runAction(action, {})
  }

  function runAction(action: ResourceAction, params: Record<string, string>) {
    setPendingAction(null)
    setError(null)
    runResourceAction(resourceId, action.id, {
      scope,
      keys: action.scope_mode === 'selection' ? [...selected] : [],
      params,
    })
      .then((handle) => watch(handle.job_id))
      .catch(handleApiError)
  }

  if (loading && !spec) {
    return <div className="resource-panel resource-panel-loading">Loading {resourceId}...</div>
  }
  if (!spec) {
    return (
      <div className="resource-panel">
        <div className="error-banner">
          {error || `Resource ${resourceId} is not registered on the backend.`}
        </div>
      </div>
    )
  }

  const syncRow = spec.sync_state.find((s) => s.scope === scope)
  const blockedSelection = spec.has_deps
    ? [...selected].filter((k) => {
        const item = items.find((i) => i.key === k)
        return (item?.deps_count ?? 0) > 0
      })
    : []

  return (
    <div className="resource-panel">
      <div className="resource-panel-head">
        <button
          type="button"
          className="resource-panel-title"
          onClick={() => setCollapsed((v) => !v)}
        >
          <span className={`sidebar-caret ${collapsed ? '' : 'open'}`}>&#9656;</span>
          <h2>{spec.label}</h2>
          <span className="pill pill-info">{spec.service}</span>
          <span className="cell-muted">{spec.cached_items} cached</span>
        </button>
        {syncRow && (
          <span className={`resource-sync-state ${syncRow.status === 'ok' ? '' : 'sync-error'}`}>
            {syncRow.status === 'ok'
              ? `Synced ${new Date(syncRow.synced_at).toLocaleString()}`
              : `Last sync failed: ${syncRow.message}`}
          </span>
        )}
      </div>

      {!collapsed && (
        <>
          {spec.description && <p className="resource-panel-desc">{spec.description}</p>}

          <div className="resource-controls">
            <label className="resource-scope">
              <span>{spec.service === 'CUBE' ? 'Router' : spec.service === 'WEBEX' ? 'Org' : 'Cluster'}</span>
              <select value={scope} onChange={(e) => changeScope(e.target.value)}>
                {spec.targets.length === 0 && <option value="">none defined</option>}
                {spec.targets.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}
                    {t.server ? ` (${t.server})` : ''}
                    {t.ready ? '' : ' - locked'}
                  </option>
                ))}
              </select>
            </label>

            {spec.filters.map((field) => (
              <label key={field.name} className="resource-filter-field">
                <span>{field.label}</span>
                {field.kind === 'bool' ? (
                  <input
                    type="checkbox"
                    checked={(filters[field.name] ?? field.default) === 'true'}
                    onChange={(e) =>
                      setFilters((prev) => ({
                        ...prev,
                        [field.name]: e.target.checked ? 'true' : 'false',
                      }))
                    }
                  />
                ) : (
                  <input
                    type={field.kind === 'number' ? 'number' : 'text'}
                    value={filters[field.name] ?? field.default}
                    placeholder={field.placeholder}
                    title={field.help}
                    onChange={(e) =>
                      setFilters((prev) => ({ ...prev, [field.name]: e.target.value }))
                    }
                  />
                )}
              </label>
            ))}

            {spec.has_deps && (
              <label className="checkbox-label" title={spec.deps_label}>
                <input
                  type="checkbox"
                  checked={includeDeps}
                  onChange={(e) => setIncludeDeps(e.target.checked)}
                />
                Include dependencies
              </label>
            )}

            <button className="btn btn-primary" onClick={handleSync} disabled={running}>
              {running && job?.kind === 'sync' ? 'Syncing...' : 'Sync'}
            </button>

            {spec.has_deps && (
              <button
                className="btn btn-secondary"
                onClick={handleScanDeps}
                disabled={running || selected.size === 0}
                title="Check dependencies for the ticked rows only"
              >
                Check dependencies
              </button>
            )}

            <a
              className="btn btn-secondary"
              href={getResourceExportUrl(resourceId, scope)}
              download
            >
              Export CSV
            </a>

            {target && !target.ready && (
              <button
                className="btn btn-secondary"
                onClick={() =>
                  setUnlockFor({ name: scope, message: `${spec.service} ${scope} is locked.` })
                }
              >
                Unlock
              </button>
            )}
          </div>

          {visibleActions.length > 0 && (
            <div className="resource-actions">
              {visibleActions.map((action) => {
                const needsRows = action.scope_mode === 'selection'
                return (
                  <button
                    key={action.id}
                    className={`btn btn-${action.style}`}
                    disabled={running || (needsRows && selected.size === 0)}
                    title={action.help || undefined}
                    onClick={() => startAction(action)}
                  >
                    {action.label}
                    {needsRows && selected.size > 0 ? ` (${selected.size})` : ''}
                  </button>
                )
              })}
            </div>
          )}

          {spec.sync_note && <div className="field-hint">{spec.sync_note}</div>}

          {blockedSelection.length > 0 && (
            <div className="field-hint field-hint-warn">
              {blockedSelection.length} of the ticked rows are in use. An action that refuses
              in-use rows will skip them and say so.
            </div>
          )}

          {error && <div className="error-banner">{error}</div>}

          <JobPanel job={job} log={log} onStop={stop} onDismiss={clear} />

          <ResourceTable
            columns={spec.columns}
            items={items}
            keyLabel={spec.key_label}
            hasDeps={spec.has_deps}
            depsLabel={spec.deps_label}
            protectedKeys={spec.protected_keys}
            selected={selected}
            onSelectedChange={setSelected}
            showScope={new Set(items.map((i) => i.scope)).size > 1}
            emptyMessage={
              target && !target.ready
                ? `${spec.service} ${scope} is locked. Unlock it, then press Sync.`
                : 'Nothing cached yet. Press Sync to pull it in.'
            }
          />
        </>
      )}

      {pendingAction && (
        <ActionDialog
          action={pendingAction}
          keys={pendingAction.scope_mode === 'selection' ? [...selected] : []}
          scope={scope}
          resourceLabel={spec.label}
          onCancel={() => setPendingAction(null)}
          onConfirm={(params) => runAction(pendingAction, params)}
        />
      )}

      {unlockFor && (
        <UnlockDialog
          service={spec.service}
          target={spec.targets.find((t) => t.name === unlockFor.name) ?? null}
          name={unlockFor.name}
          message={unlockFor.message}
          onCancel={() => setUnlockFor(null)}
          onUnlocked={() => {
            setUnlockFor(null)
            reload(scope)
          }}
        />
      )}
    </div>
  )
}
