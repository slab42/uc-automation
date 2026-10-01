import { useState } from 'react'
import { unlockConnection } from '../api'
import type { ConnectionTarget } from '../types'

/**
 * Ask for the password of a target whose credentials.env entry is blank.
 *
 * This is the web equivalent of the getpass() prompt the terminal scripts
 * use, and it keeps the same guarantee: the value is typed into a password
 * field, posted once, held in the server process's memory for as long as it
 * runs, and never written to disk or echoed anywhere. To store it
 * permanently the operator uses the Settings page, which edits
 * .env/credentials.env.
 */

export interface UnlockDialogProps {
  service: string
  target: ConnectionTarget | null
  /** Target name, for the case where we have no full target row. */
  name: string
  username?: string
  message?: string
  onCancel: () => void
  onUnlocked: () => void
}

export default function UnlockDialog({
  service,
  target,
  name,
  username,
  message,
  onCancel,
  onUnlocked,
}: UnlockDialogProps) {
  const secretKey = target?.secret_key || (service === 'WEBEX' ? 'api_token' : 'password')
  const isToken = secretKey === 'api_token'
  const [user, setUser] = useState(target?.username || username || '')
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function submit() {
    if (!secret) return
    setBusy(true)
    setError(null)
    unlockConnection(service, name, secret, user)
      .then(() => {
        setSecret('')
        onUnlocked()
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="doc-modal-backdrop" onClick={onCancel}>
      <div className="action-dialog" onClick={(e) => e.stopPropagation()}>
        <h2>
          Unlock {service} {name}
        </h2>
        {message && <p className="action-dialog-help">{message}</p>}
        <p className="action-dialog-help">
          {isToken
            ? 'This Webex org has no api_token saved. The token is kept in the server process only, for as long as it runs.'
            : 'This target has no password saved. It is kept in the server process only, for as long as it runs. To store it, use Settings.'}
        </p>

        {!isToken && (
          <div className="option-field">
            <label htmlFor="unlock-username">Username</label>
            <input
              id="unlock-username"
              type="text"
              autoComplete="username"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              placeholder={target?.username || 'admin user'}
            />
          </div>
        )}

        <div className="option-field">
          <label htmlFor="unlock-secret">{isToken ? 'Access token' : 'Password'}</label>
          <input
            id="unlock-secret"
            type="password"
            autoComplete="new-password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit()
            }}
            autoFocus
          />
        </div>

        {error && <div className="field-hint field-hint-warn">{error}</div>}

        <div className="settings-edit-actions">
          <button className="btn btn-primary" disabled={!secret || busy} onClick={submit}>
            {busy ? 'Unlocking...' : 'Unlock'}
          </button>
          <button className="btn btn-secondary" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
