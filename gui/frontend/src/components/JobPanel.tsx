import { useState } from 'react'
import type { JobStatus } from '../types'

/**
 * Progress, result and log for one backend job.
 *
 * This is what replaced the scrolling CLI output: the headline is a
 * progress bar and a per-row result table, and the raw log is collapsed
 * behind a disclosure for when something needs digging into. A finished
 * action shows which rows succeeded and which did not, because a bulk
 * delete where three of forty rows failed is the case that matters.
 */

export interface JobPanelProps {
  job: JobStatus | null
  log: string[]
  onStop?: () => void
  onDismiss?: () => void
}

function statusTone(status: JobStatus['status']): string {
  switch (status) {
    case 'done':
      return 'ok'
    case 'error':
      return 'danger'
    case 'cancelled':
      return 'warn'
    default:
      return 'info'
  }
}

export default function JobPanel({ job, log, onStop, onDismiss }: JobPanelProps) {
  const [showLog, setShowLog] = useState(false)
  if (!job) return null

  const running = job.status === 'running'
  const pct =
    job.total && job.total > 0 ? Math.min(100, Math.round((job.done / job.total) * 100)) : null
  const results = job.result?.results ?? []
  const failures = results.filter((r) => !r.success)
  const successes = results.filter((r) => r.success)

  return (
    <div className={`job-panel job-${job.status}`}>
      <div className="job-panel-head">
        <span className={`pill pill-${statusTone(job.status)}`}>{job.status}</span>
        <strong>{job.label}</strong>
        <span className="job-panel-spacer" />
        {running && onStop && (
          <button className="btn btn-danger btn-sm" onClick={onStop}>
            Stop
          </button>
        )}
        {!running && onDismiss && (
          <button className="btn btn-secondary btn-sm" onClick={onDismiss}>
            Dismiss
          </button>
        )}
      </div>

      {running && (
        <div className="job-progress">
          <div className="job-progress-bar">
            <div
              className={`job-progress-fill ${pct === null ? 'indeterminate' : ''}`}
              style={pct === null ? undefined : { width: `${pct}%` }}
            />
          </div>
          <span className="job-progress-text">
            {job.total ? `${job.done} / ${job.total}` : 'working'}
          </span>
        </div>
      )}

      {job.message && <div className="job-message">{job.message}</div>}
      {job.error && <div className="job-error">{job.error}</div>}

      {!running && job.result?.item_count !== undefined && (
        <div className="job-message">Cached {job.result.item_count} row(s).</div>
      )}

      {!running && (job.result?.outcomes?.length ?? 0) > 0 && (
        <ul className="job-outcomes">
          {job.result?.outcomes?.map((outcome, i) => {
            const scope = String(outcome.scope ?? '')
            const error = outcome.error ? String(outcome.error) : null
            return (
              <li key={`${scope}-${i}`}>
                <span className={`pill pill-${error ? 'danger' : 'ok'}`}>
                  {error ? 'failed' : 'ok'}
                </span>
                <strong>{scope}</strong>
                {error ? (
                  <span> {error}</span>
                ) : (
                  <span>
                    {' '}
                    {String(outcome.item_count ?? 0)} row(s)
                    {outcome.deps_included ? ', dependencies included' : ''}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {results.length > 0 && (
        <div className="job-results">
          <div className="job-results-head">
            {successes.length} succeeded, {failures.length} failed
          </div>
          {failures.length > 0 && (
            <table className="resource-table job-results-table">
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Why it did not run</th>
                </tr>
              </thead>
              <tbody>
                {failures.map((r) => (
                  <tr key={r.key}>
                    <td className="col-key">{r.key || '-'}</td>
                    <td>{r.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {log.length > 0 && (
        <div className="job-log-wrap">
          <button type="button" className="btn-link" onClick={() => setShowLog((v) => !v)}>
            {showLog ? 'Hide' : 'Show'} log ({log.length} lines)
          </button>
          {showLog && (
            <pre className="activity-log job-log">
              {log.map((line, i) => (
                <div key={i} className="activity-log-line">
                  {line || ' '}
                </div>
              ))}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
