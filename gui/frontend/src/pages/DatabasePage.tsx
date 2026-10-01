import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  NeedsCredentialsError,
  clearDb,
  forgetConnections,
  getConnections,
  getDbActions,
  getDbOverview,
  syncWholeDb,
} from '../api'
import JobPanel from '../components/JobPanel'
import UnlockDialog from '../components/UnlockDialog'
import { useJob } from '../hooks/useJob'
import type { ActionLogRow, ConnectionsResponse, DbOverview } from '../types'

/**
 * The local database: what is cached, how fresh it is, and one button to
 * refetch all of it.
 *
 * Every resource page reads its rows from this SQLite file rather than
 * calling CUCM / CUC / Webex again, which is what makes the pages open
 * instantly. This page is where that cache is managed: per-resource row
 * counts and sync times, "Sync DB" to refetch everything that has a usable
 * password, the connection list with its unlock state, the log of what was
 * actually changed on a UC system from this GUI, and Clear when a rebuild
 * from scratch is wanted.
 */

function formatBytes(value: number): string {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const exp = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** exp).toFixed(exp === 0 ? 0 : 1)} ${units[exp]}`
}

function formatWhen(value: string | null): string {
  if (!value) return 'never'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export default function DatabasePage() {
  const [overview, setOverview] = useState<DbOverview | null>(null)
  const [connections, setConnections] = useState<ConnectionsResponse | null>(null)
  const [actions, setActions] = useState<ActionLogRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [includeDeps, setIncludeDeps] = useState(false)
  const [unlockFor, setUnlockFor] = useState<{ service: string; name: string } | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)

  const reload = useCallback(() => {
    getDbOverview().then(setOverview).catch((e) => setError(String(e)))
    getConnections().then(setConnections).catch(() => undefined)
    getDbActions(50)
      .then((res) => setActions(res.actions))
      .catch(() => undefined)
  }, [])

  useEffect(reload, [reload])

  const { job, log, running, watch, stop, clear } = useJob(reload)

  const readyCount = useMemo(
    () =>
      (connections?.services ?? []).reduce(
        (total, svc) => total + svc.targets.filter((t) => t.ready).length,
        0,
      ),
    [connections],
  )

  function handleSyncAll() {
    setError(null)
    syncWholeDb({ include_deps: includeDeps })
      .then((handle) => watch(handle.job_id))
      .catch((err) => {
        if (err instanceof NeedsCredentialsError) {
          setError(err.message)
          return
        }
        setError(err instanceof Error ? err.message : String(err))
      })
  }

  function handleClear() {
    setConfirmClear(false)
    clearDb()
      .then(reload)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  function handleForgetAll() {
    forgetConnections().then(reload).catch(() => undefined)
  }

  const stats = overview?.stats
  const byService = useMemo(() => {
    const groups: Record<string, DbOverview['resources']> = {}
    for (const row of overview?.resources ?? []) {
      groups[row.service] = groups[row.service] || []
      groups[row.service].push(row)
    }
    return groups
  }, [overview])

  return (
    <div className="page">
      <div className="script-header">
        <h1>Database</h1>
        <div className="script-meta">
          <span className="script-rel">{stats?.path ?? '_DATA/uc_cache.db'}</span>
        </div>
      </div>

      <p className="settings-note">
        Resource pages read from this local cache instead of calling a UC system on every view.
        Sync DB refetches everything that has a usable password. Clearing it is always safe: the
        next sync rebuilds it.
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="db-stat-row">
        <div className="db-stat">
          <span className="db-stat-value">{stats?.item_count.toLocaleString() ?? '-'}</span>
          <span className="db-stat-label">cached rows</span>
        </div>
        <div className="db-stat">
          <span className="db-stat-value">{stats?.resource_count ?? '-'}</span>
          <span className="db-stat-label">resources with data</span>
        </div>
        <div className="db-stat">
          <span className="db-stat-value">{stats?.scope_count ?? '-'}</span>
          <span className="db-stat-label">systems</span>
        </div>
        <div className="db-stat">
          <span className="db-stat-value">{stats ? formatBytes(stats.size_bytes) : '-'}</span>
          <span className="db-stat-label">file size</span>
        </div>
        <div className="db-stat">
          <span className="db-stat-value">{formatWhen(stats?.last_sync ?? null)}</span>
          <span className="db-stat-label">last sync</span>
        </div>
      </div>

      <div className="resource-controls">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={includeDeps}
            onChange={(e) => setIncludeDeps(e.target.checked)}
          />
          Include dependency scans
        </label>
        <button className="btn btn-primary" onClick={handleSyncAll} disabled={running}>
          {running ? 'Syncing...' : 'Sync DB'}
        </button>
        <button
          className="btn btn-danger"
          onClick={() => setConfirmClear(true)}
          disabled={running || !stats?.item_count}
        >
          Clear cache
        </button>
        <span className="cell-muted">
          {readyCount} of{' '}
          {(connections?.services ?? []).reduce((t, s) => t + s.targets.length, 0)} systems ready
        </span>
      </div>

      {includeDeps && (
        <div className="field-hint field-hint-warn">
          A dependency scan is several queries per row on every resource that has one. On a large
          cluster this turns a one-minute sync into a long one.
        </div>
      )}

      {confirmClear && (
        <div className="doc-modal-backdrop" onClick={() => setConfirmClear(false)}>
          <div className="action-dialog" onClick={(e) => e.stopPropagation()}>
            <h2>Clear the cache?</h2>
            <p className="action-dialog-help">
              This forgets {stats?.item_count.toLocaleString()} cached rows and every sync time.
              Nothing on any UC system is touched, and the next sync rebuilds it.
            </p>
            <div className="settings-edit-actions">
              <button className="btn btn-danger" onClick={handleClear}>
                Clear cache
              </button>
              <button className="btn btn-secondary" onClick={() => setConfirmClear(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <JobPanel job={job} log={log} onStop={stop} onDismiss={clear} />

      <div className="settings-cards">
        {Object.entries(byService).map(([service, rows]) => (
          <div key={service} className="settings-card">
            <h2>{service}</h2>
            <table className="resource-table">
              <thead>
                <tr>
                  <th>Resource</th>
                  <th>Rows</th>
                  <th>Systems synced</th>
                  <th>Last sync</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const last = row.sync_state
                    .map((s) => s.synced_at)
                    .sort()
                    .pop()
                  const failed = row.sync_state.filter((s) => s.status !== 'ok')
                  return (
                    <tr key={row.id}>
                      <td className="col-key">
                        {row.label}
                        <span className="cell-muted"> {row.id}</span>
                      </td>
                      <td className="cell-number">{row.cached_items.toLocaleString()}</td>
                      <td>
                        {row.sync_state.length === 0 ? (
                          <span className="cell-no">-</span>
                        ) : (
                          <span className="cell-pills">
                            {row.sync_state.map((s) => (
                              <span
                                key={s.scope}
                                className={`pill pill-${s.status === 'ok' ? 'ok' : 'danger'}`}
                                title={s.message || undefined}
                              >
                                {s.scope}
                              </span>
                            ))}
                          </span>
                        )}
                      </td>
                      <td className="cell-muted">
                        {formatWhen(last ?? null)}
                        {failed.length > 0 && (
                          <span className="pill pill-danger">{failed.length} failed</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      <div className="settings-card">
        <h2>Connections</h2>
        <p className="settings-note">
          A locked system has no password in <code>.env/credentials.env</code>. Unlocking holds one
          in this server process only; to save it, use <Link to="/settings">Settings</Link>.
        </p>
        <table className="resource-table">
          <thead>
            <tr>
              <th>System</th>
              <th>Service</th>
              <th>Address</th>
              <th>Username</th>
              <th>State</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(connections?.services ?? []).flatMap((svc) =>
              svc.targets.map((t) => (
                <tr key={`${svc.service}-${t.name}`}>
                  <td className="col-key">{t.name}</td>
                  <td>
                    <span className="pill pill-info">{svc.service}</span>
                  </td>
                  <td className="cell-muted">
                    {t.server}
                    {t.version ? ` v${t.version}` : ''}
                  </td>
                  <td className="cell-muted">{t.username || '-'}</td>
                  <td>
                    {t.unlocked ? (
                      <span className="pill pill-ok">unlocked (memory)</span>
                    ) : t.has_stored_secret ? (
                      <span className="pill pill-ok">saved</span>
                    ) : (
                      <span className="pill pill-warn">locked</span>
                    )}
                  </td>
                  <td>
                    {!t.ready && (
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => setUnlockFor({ service: svc.service, name: t.name })}
                      >
                        Unlock
                      </button>
                    )}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
        <div className="settings-edit-actions">
          <button className="btn btn-secondary btn-sm" onClick={handleForgetAll}>
            Forget held passwords
          </button>
        </div>
      </div>

      <div className="settings-card">
        <h2>Change log</h2>
        <p className="settings-note">
          What this GUI changed on a UC system. Syncs are reads and are not listed.
        </p>
        {actions.length === 0 ? (
          <p className="settings-empty">Nothing yet.</p>
        ) : (
          <table className="resource-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Resource</th>
                <th>System</th>
                <th>Action</th>
                <th>Row</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {actions.map((row) => (
                <tr key={row.id}>
                  <td className="cell-muted">{formatWhen(row.at)}</td>
                  <td>{row.resource}</td>
                  <td>{row.scope}</td>
                  <td>{row.action}</td>
                  <td className="col-key">{row.item_key || '-'}</td>
                  <td>
                    <span className={`pill pill-${row.success ? 'ok' : 'danger'}`}>
                      {row.success ? 'ok' : 'failed'}
                    </span>
                    {row.message && <span className="cell-muted"> {row.message}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {unlockFor && (
        <UnlockDialog
          service={unlockFor.service}
          target={
            connections?.services
              .find((s) => s.service === unlockFor.service)
              ?.targets.find((t) => t.name === unlockFor.name) ?? null
          }
          name={unlockFor.name}
          onCancel={() => setUnlockFor(null)}
          onUnlocked={() => {
            setUnlockFor(null)
            reload()
          }}
        />
      )}
    </div>
  )
}
