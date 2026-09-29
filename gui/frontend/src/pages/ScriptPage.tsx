import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useScripts } from '../App'
import { buildWsUrl, getScript, uploadDataFile } from '../api'
import DocModal from '../components/DocModal'
import type { PromptMessage, ScriptInfo, ScriptOption, WsServerMessage } from '../types'

type RunStatus =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'waiting' }
  | { kind: 'exited'; code: number }
  | { kind: 'error'; message: string }

interface LogLine {
  id: number
  text: string
  open?: boolean
}

function quoteIfNeeded(value: string): string {
  if (value === '') return value
  if (/\s/.test(value)) return `"${value.replace(/"/g, '\\"')}"`
  return value
}

function longestFlag(flags: string[]): string {
  if (flags.length === 0) return ''
  return flags.reduce((a, b) => (b.length > a.length ? b : a))
}

function buildArgsPreview(
  options: ScriptOption[],
  values: Record<string, string>,
  bools: Record<string, boolean>,
  extra: string,
): string {
  const parts: string[] = []
  const positionals = options.filter((o) => o.positional)
  const flagsOpts = options.filter((o) => !o.positional)

  for (const opt of flagsOpts) {
    if (opt.action === 'store_true' || opt.action === 'store_false') {
      if (bools[opt.dest]) parts.push(longestFlag(opt.flags))
      continue
    }
    const v = values[opt.dest]
    if (v !== undefined && v !== '') {
      parts.push(longestFlag(opt.flags))
      parts.push(quoteIfNeeded(v))
    }
  }

  for (const opt of positionals) {
    const v = values[opt.dest]
    if (v !== undefined && v !== '') {
      parts.push(quoteIfNeeded(v))
    }
  }

  if (extra.trim()) {
    parts.push(extra.trim())
  }

  return parts.join(' ')
}

export default function ScriptPage() {
  const params = useParams()
  const rel = params['*'] ?? ''
  const { categories } = useScripts()

  const fromContext = useMemo<ScriptInfo | null>(() => {
    for (const cat of categories) {
      const found = cat.scripts.find((s) => s.rel === rel)
      if (found) return found
    }
    return null
  }, [categories, rel])

  const [script, setScript] = useState<ScriptInfo | null>(fromContext)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [status, setStatus] = useState<RunStatus>({ kind: 'idle' })
  const [showDoc, setShowDoc] = useState(false)

  const [optionValues, setOptionValues] = useState<Record<string, string>>({})
  const [optionBools, setOptionBools] = useState<Record<string, boolean>>({})
  const [extraArgs, setExtraArgs] = useState('')
  const [showExtra, setShowExtra] = useState(false)

  const [logLines, setLogLines] = useState<LogLine[]>([])
  const [prompt, setPrompt] = useState<PromptMessage | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const sawExitRef = useRef(false)
  const logIdRef = useRef(0)
  const logEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setScript(fromContext)
  }, [fromContext])

  useEffect(() => {
    if (fromContext || !rel) return
    let cancelled = false
    getScript(rel)
      .then((s) => {
        if (!cancelled) setScript(s)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [rel, fromContext])

  // Reset per-script form state when navigating to a different script.
  useEffect(() => {
    setOptionValues({})
    setOptionBools({})
    setExtraArgs('')
    setShowExtra(false)
    setLogLines([])
    setPrompt(null)
    setStatus({ kind: 'idle' })
  }, [rel])

  // Close the socket whenever we navigate away from this script.
  useEffect(() => {
    return () => {
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [rel])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: 'end' })
  }, [logLines])

  const options = script?.options ?? []
  const hasOptionsForm = options.length > 0 || script?.takes_args === true
  const extraExpanded = options.length === 0 && (script?.takes_args ?? false)

  // Output arrives in arbitrary chunks. A chunk that does not end with a
  // newline (typically a prompt such as "Select cluster [1-8]: ") leaves the
  // last line open so the next chunk (the echoed answer) continues it. The
  // open flag lives on the line itself because React batches these updates.
  function appendLog(text: string) {
    if (!text) return
    setLogLines((prev) => {
      const pieces = text.split('\n')
      const next = [...prev]
      let continuing = next.length > 0 && next[next.length - 1].open === true
      for (let i = 0; i < pieces.length; i++) {
        const piece = pieces[i]
        if (i === pieces.length - 1 && piece === '') break
        if (continuing) {
          const last = next[next.length - 1]
          next[next.length - 1] = { ...last, text: last.text + piece, open: false }
          continuing = false
        } else {
          logIdRef.current += 1
          next.push({ id: logIdRef.current, text: piece, open: false })
        }
      }
      if (!text.endsWith('\n') && next.length > 0) {
        next[next.length - 1] = { ...next[next.length - 1], open: true }
      } else if (next.length > 0 && prev.length > 0 && next[next.length - 1].open) {
        next[next.length - 1] = { ...next[next.length - 1], open: false }
      }
      return next
    })
  }

  function closeSocket() {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }

  function requiredMissing(): boolean {
    for (const opt of options) {
      if (!opt.required) continue
      if (opt.action === 'store_true' || opt.action === 'store_false') continue
      const v = optionValues[opt.dest]
      if (!v || v.trim() === '') return true
    }
    return false
  }

  function handleRun() {
    if (!script) return
    closeSocket()
    sawExitRef.current = false
    setPrompt(null)

    const now = new Date()
    const timeStr = now.toLocaleTimeString()
    setLogLines((prev) => {
      const next = [...prev]
      logIdRef.current += 1
      next.push({ id: logIdRef.current, text: `----- run started ${timeStr} -----`, open: false })
      return next
    })

    const args = buildArgsPreview(options, optionValues, optionBools, extraArgs)
    const url = buildWsUrl(script.rel, args)
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onmessage = (ev) => {
      let msg: WsServerMessage
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      switch (msg.type) {
        case 'started':
          setStatus({ kind: 'running' })
          break
        case 'output':
          appendLog(msg.data)
          break
        case 'prompt':
          setPrompt(msg)
          setStatus({ kind: 'waiting' })
          break
        case 'exit':
          sawExitRef.current = true
          setPrompt(null)
          setStatus({ kind: 'exited', code: msg.code })
          break
        case 'error':
          setStatus({ kind: 'error', message: msg.message })
          break
      }
    }

    ws.onclose = () => {
      if (!sawExitRef.current) {
        setStatus((prev) =>
          prev.kind === 'running' || prev.kind === 'idle' || prev.kind === 'waiting'
            ? { kind: 'error', message: 'Connection error' }
            : prev,
        )
      }
      wsRef.current = null
    }

    ws.onerror = () => {
      // onclose will follow and set status
    }
  }

  function handleStop() {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'kill' }))
    }
  }

  function sendAnswer(id: number, value: string) {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'answer', id, value }))
    }
    setPrompt(null)
    setStatus({ kind: 'running' })
  }

  function handleClearLog() {
    setLogLines([])
  }

  if (loadError) {
    return (
      <div className="page">
        <div className="error-banner">Could not load script: {loadError}</div>
      </div>
    )
  }

  if (!script) {
    return (
      <div className="page">
        <p>Loading script...</p>
      </div>
    )
  }

  const isRunning = status.kind === 'running' || status.kind === 'waiting'
  let statusText: string
  switch (status.kind) {
    case 'idle':
      statusText = 'Idle'
      break
    case 'running':
      statusText = 'Running'
      break
    case 'waiting':
      statusText = 'Waiting for your input'
      break
    case 'exited':
      statusText = `Exited with code ${status.code}`
      break
    case 'error':
      statusText = status.message || 'Connection error'
      break
  }

  const commandPreview = `python3 ${script.filename} ${buildArgsPreview(
    options,
    optionValues,
    optionBools,
    extraArgs,
  )}`.trim()

  return (
    <div className="page script-page">
      <div className="script-header">
        <h1>{script.title}</h1>
        <div className="script-meta">
          <span className="script-rel">{script.rel}</span>
          <span className="script-category-badge">{script.category}</span>
        </div>
        <button className="btn btn-secondary" onClick={() => setShowDoc(true)}>
          View description
        </button>
      </div>

      {hasOptionsForm && (
        <div className="options-card">
          <h3>Options</h3>
          {options.map((opt) => (
            <OptionField
              key={opt.dest}
              option={opt}
              value={optionValues[opt.dest] ?? ''}
              boolValue={optionBools[opt.dest] ?? false}
              onValueChange={(v) => setOptionValues((prev) => ({ ...prev, [opt.dest]: v }))}
              onBoolChange={(v) => setOptionBools((prev) => ({ ...prev, [opt.dest]: v }))}
            />
          ))}

          <div className="additional-args">
            {!extraExpanded && !showExtra ? (
              <button
                type="button"
                className="btn-link"
                onClick={() => setShowExtra(true)}
              >
                Additional arguments
              </button>
            ) : (
              <div className="script-args">
                <label htmlFor="extra-args-input">Additional arguments</label>
                <input
                  id="extra-args-input"
                  type="text"
                  value={extraArgs}
                  onChange={(e) => setExtraArgs(e.target.value)}
                  placeholder=""
                />
                <div className="field-hint">Extra command-line arguments, shell-style quoting</div>
              </div>
            )}
          </div>

          <div className="command-preview mono">{commandPreview}</div>
        </div>
      )}

      <div className="script-controls">
        <button
          className="btn btn-primary"
          onClick={handleRun}
          disabled={isRunning || requiredMissing()}
        >
          Run
        </button>
        <button className="btn btn-danger" onClick={handleStop} disabled={!isRunning}>
          Stop
        </button>
        <span className={`status-line status-${status.kind}`}>{statusText}</span>
      </div>

      {prompt && (
        <PromptCard prompt={prompt} onAnswer={(value) => sendAnswer(prompt.id, value)} />
      )}

      <div className="activity-log-wrap">
        <div className="activity-log-header">
          <h3>Activity log</h3>
          <button className="btn btn-secondary btn-sm" onClick={handleClearLog}>
            Clear
          </button>
        </div>
        <pre className="activity-log">
          {logLines.map((line) => (
            <div key={line.id} className="activity-log-line">
              {line.text || ' '}
            </div>
          ))}
          <div ref={logEndRef} />
        </pre>
      </div>

      {showDoc && <DocModal script={script} onClose={() => setShowDoc(false)} />}
    </div>
  )
}

interface OptionFieldProps {
  option: ScriptOption
  value: string
  boolValue: boolean
  onValueChange: (v: string) => void
  onBoolChange: (v: boolean) => void
}

function OptionField({ option, value, boolValue, onValueChange, onBoolChange }: OptionFieldProps) {
  const label = option.positional
    ? option.metavar ?? option.dest
    : longestFlag(option.flags)

  if (option.action === 'store_true' || option.action === 'store_false') {
    return (
      <div className="option-field option-field-bool">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={boolValue}
            onChange={(e) => onBoolChange(e.target.checked)}
          />
          {label}
        </label>
        {option.help && <div className="field-hint">{option.help}</div>}
      </div>
    )
  }

  if (option.choices && option.choices.length > 0) {
    return (
      <div className="option-field">
        <label>
          {label}
          {option.required && <span className="required-tag">required</span>}
        </label>
        <select value={value} onChange={(e) => onValueChange(e.target.value)}>
          <option value="">(not set)</option>
          {option.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        {option.help && <div className="field-hint">{option.help}</div>}
      </div>
    )
  }

  const inputType = option.type === 'int' || option.type === 'float' ? 'number' : 'text'
  const placeholder = option.default ?? option.metavar ?? option.dest

  return (
    <div className="option-field">
      <label>
        {label}
        {option.required && <span className="required-tag">required</span>}
      </label>
      <input
        type={inputType}
        value={value}
        placeholder={placeholder ?? ''}
        onChange={(e) => onValueChange(e.target.value)}
      />
      {option.help && <div className="field-hint">{option.help}</div>}
    </div>
  )
}

interface PromptCardProps {
  prompt: PromptMessage
  onAnswer: (value: string) => void
}

function PromptCard({ prompt, onAnswer }: PromptCardProps) {
  const [textValue, setTextValue] = useState('')
  const [otherValue, setOtherValue] = useState('')
  const [selectedChoice, setSelectedChoice] = useState<string | null>(
    prompt.choices.find((c) => c.value === prompt.default)?.value ?? null,
  )
  const [useOther, setUseOther] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const firstFieldRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    firstFieldRef.current?.focus()
  }, [prompt.id])

  const label = prompt.label || prompt.text

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadError(null)
    setUploading(true)
    try {
      let result
      try {
        result = await uploadDataFile(file, false)
      } catch (err) {
        const conflict = (err as Error & { conflict?: boolean }).conflict
        if (conflict && confirm(`A file named "${file.name}" already exists. Overwrite it?`)) {
          result = await uploadDataFile(file, true)
        } else {
          throw err
        }
      }
      setTextValue(result.path)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  if (prompt.kind === 'yes_no') {
    const yesIsDefault = prompt.default === 'y'
    const noIsDefault = prompt.default === 'n'
    return (
      <div className="prompt-card">
        <div className="prompt-label">{label}</div>
        <div className="prompt-actions">
          <button
            ref={firstFieldRef as unknown as React.Ref<HTMLButtonElement>}
            className={`btn ${yesIsDefault ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => onAnswer('y')}
          >
            Yes{yesIsDefault ? ' (default)' : ''}
          </button>
          <button
            className={`btn ${noIsDefault ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => onAnswer('n')}
          >
            No{noIsDefault ? ' (default)' : ''}
          </button>
        </div>
      </div>
    )
  }

  if (prompt.kind === 'choice') {
    function submit() {
      if (useOther) {
        onAnswer(otherValue)
      } else if (selectedChoice !== null) {
        onAnswer(selectedChoice)
      }
    }
    return (
      <div className="prompt-card">
        <div className="prompt-label">{label}</div>
        <div className="prompt-choice-list">
          {prompt.choices.map((c, idx) => (
            <label key={c.value} className="prompt-radio-label">
              <input
                ref={idx === 0 ? firstFieldRef : undefined}
                type="radio"
                name={`prompt-${prompt.id}`}
                checked={!useOther && selectedChoice === c.value}
                onChange={() => {
                  setUseOther(false)
                  setSelectedChoice(c.value)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submit()
                }}
              />
              {c.label}
            </label>
          ))}
          {prompt.allow_other && (
            <label className="prompt-radio-label">
              <input
                type="radio"
                name={`prompt-${prompt.id}`}
                checked={useOther}
                onChange={() => setUseOther(true)}
              />
              Other:
              <input
                type="text"
                value={otherValue}
                onChange={(e) => {
                  setUseOther(true)
                  setOtherValue(e.target.value)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submit()
                }}
              />
            </label>
          )}
        </div>
        <div className="prompt-actions">
          <button className="btn btn-primary" onClick={submit}>
            Select
          </button>
        </div>
      </div>
    )
  }

  if (prompt.kind === 'secret') {
    return (
      <div className="prompt-card">
        <div className="prompt-label">{label}</div>
        <div className="prompt-actions">
          <input
            ref={firstFieldRef}
            type="password"
            value={textValue}
            onChange={(e) => setTextValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onAnswer(textValue)
            }}
          />
          <button className="btn btn-primary" onClick={() => onAnswer(textValue)}>
            Submit
          </button>
        </div>
      </div>
    )
  }

  if (prompt.kind === 'file') {
    return (
      <div className="prompt-card">
        <div className="prompt-label">{label}</div>
        <div className="prompt-actions">
          <input
            ref={firstFieldRef}
            type="text"
            list={`prompt-suggestions-${prompt.id}`}
            value={textValue}
            placeholder={prompt.default || ''}
            onChange={(e) => setTextValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onAnswer(textValue)
            }}
          />
          <datalist id={`prompt-suggestions-${prompt.id}`}>
            {prompt.suggestions.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </datalist>
          <button className="btn btn-primary" onClick={() => onAnswer(textValue)}>
            Use this file
          </button>
        </div>
        {prompt.default && <div className="field-hint">Leave blank to use the default</div>}
        <div className="prompt-upload">
          <label className="btn btn-secondary btn-sm upload-btn">
            {uploading ? 'Uploading...' : 'Upload'}
            <input
              type="file"
              accept=".csv,.txt,.xlsx"
              onChange={handleFileUpload}
              disabled={uploading}
              style={{ display: 'none' }}
            />
          </label>
        </div>
        {uploadError && <div className="error-banner">{uploadError}</div>}
      </div>
    )
  }

  if (prompt.kind === 'continue') {
    return (
      <div className="prompt-card">
        <div className="prompt-label">{label}</div>
        <div className="prompt-actions">
          <button
            ref={firstFieldRef as unknown as React.Ref<HTMLButtonElement>}
            className="btn btn-primary"
            onClick={() => onAnswer('')}
          >
            Continue
          </button>
        </div>
      </div>
    )
  }

  // text (default)
  return (
    <div className="prompt-card">
      <div className="prompt-label">{label}</div>
      <div className="prompt-actions">
        <input
          ref={firstFieldRef}
          type="text"
          value={textValue}
          placeholder={prompt.default || ''}
          onChange={(e) => setTextValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onAnswer(textValue)
          }}
        />
        <button className="btn btn-primary" onClick={() => onAnswer(textValue)}>
          Submit
        </button>
      </div>
    </div>
  )
}
