import { useMemo, useState } from 'react'
import type { ResourceColumn, ResourceItem } from '../types'

/**
 * The table every resource page is built around.
 *
 * It is generic on purpose: columns, their kinds and the dependency column
 * all come from the ResourceSpec the API returns, so a new resource on the
 * backend gets a full table here with no frontend change.
 *
 * Selection is the point of the thing. Every row carries a checkbox, the
 * header carries select-all for the rows currently passing the filter (not
 * the whole set, which would be a nasty surprise), and rows the system will
 * not let you change are shown greyed with the checkbox disabled rather
 * than hidden, so the operator can see why.
 */

export interface ResourceTableProps {
  columns: ResourceColumn[]
  items: ResourceItem[]
  keyLabel: string
  hasDeps: boolean
  depsLabel: string
  protectedKeys: string[]
  selected: Set<string>
  onSelectedChange: (next: Set<string>) => void
  /** Show the scope column when rows from more than one system are mixed. */
  showScope?: boolean
  emptyMessage?: string
}

type SortDir = 'asc' | 'desc'

const KEY_COL = '__key__'
const SCOPE_COL = '__scope__'
const DEPS_COL = '__deps__'

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exp = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const scaled = value / 1024 ** exp
  return `${scaled >= 10 || exp === 0 ? Math.round(scaled) : scaled.toFixed(1)} ${units[exp]}`
}

function formatDate(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

/** Everything a row contributes to the free-text filter. */
function searchBlob(item: ResourceItem): string {
  return [item.key, item.scope, ...Object.values(item.fields).map(asText)]
    .join(' ')
    .toLowerCase()
}

function sortValue(item: ResourceItem, colKey: string): string | number {
  if (colKey === KEY_COL) return item.key.toLowerCase()
  if (colKey === SCOPE_COL) return item.scope.toLowerCase()
  if (colKey === DEPS_COL) return item.deps_count ?? -1
  const raw = item.fields[colKey]
  if (typeof raw === 'number') return raw
  if (typeof raw === 'boolean') return raw ? 1 : 0
  if (raw === null || raw === undefined) return ''
  const text = String(raw)
  // A numeric-looking column (extensions, counts) should sort numerically.
  const numeric = Number(text)
  return text !== '' && !Number.isNaN(numeric) ? numeric : text.toLowerCase()
}

export default function ResourceTable({
  columns,
  items,
  keyLabel,
  hasDeps,
  depsLabel,
  protectedKeys,
  selected,
  onSelectedChange,
  showScope = false,
  emptyMessage = 'Nothing cached yet. Press Sync to pull it in.',
}: ResourceTableProps) {
  const [filter, setFilter] = useState('')
  const [sortKey, setSortKey] = useState<string>(KEY_COL)
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(
    () => new Set(columns.filter((c) => c.optional).map((c) => c.key)),
  )
  const [showColumnPicker, setShowColumnPicker] = useState(false)

  const protectedSet = useMemo(() => new Set(protectedKeys), [protectedKeys])

  // The dependency column is declared as a kind, but it is rendered from
  // deps_count / deps rather than from fields, so pull it out of the list.
  const dataColumns = useMemo(
    () => columns.filter((c) => c.kind !== 'deps' && !hiddenCols.has(c.key)),
    [columns, hiddenCols],
  )
  const depsColumn = useMemo(() => columns.find((c) => c.kind === 'deps'), [columns])

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const rows = needle ? items.filter((i) => searchBlob(i).includes(needle)) : items.slice()
    rows.sort((a, b) => {
      const av = sortValue(a, sortKey)
      const bv = sortValue(b, sortKey)
      if (av === bv) return a.key.localeCompare(b.key)
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv))
      return sortDir === 'asc' ? cmp : -cmp
    })
    return rows
  }, [items, filter, sortKey, sortDir])

  const selectableKeys = useMemo(
    () => visible.filter((i) => !protectedSet.has(i.key)).map((i) => i.key),
    [visible, protectedSet],
  )
  const allVisibleSelected =
    selectableKeys.length > 0 && selectableKeys.every((k) => selected.has(k))

  function toggleSort(colKey: string) {
    if (sortKey === colKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(colKey)
      setSortDir('asc')
    }
  }

  function toggleRow(key: string) {
    const next = new Set(selected)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    onSelectedChange(next)
  }

  function selectAllVisible() {
    const next = new Set(selected)
    selectableKeys.forEach((k) => next.add(k))
    onSelectedChange(next)
  }

  function unselectAllVisible() {
    const next = new Set(selected)
    selectableKeys.forEach((k) => next.delete(k))
    onSelectedChange(next)
  }

  function toggleExpanded(key: string) {
    const next = new Set(expanded)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setExpanded(next)
  }

  function renderCell(item: ResourceItem, col: ResourceColumn) {
    const raw = item.fields[col.key]
    switch (col.kind) {
      case 'number': {
        const n = typeof raw === 'number' ? raw : Number(raw)
        return <span className="cell-number">{Number.isNaN(n) ? '' : n.toLocaleString()}</span>
      }
      case 'bytes': {
        const n = typeof raw === 'number' ? raw : Number(raw)
        return <span className="cell-number">{Number.isNaN(n) ? '' : formatBytes(n)}</span>
      }
      case 'bool':
        return raw ? <span className="cell-yes">Yes</span> : <span className="cell-no">-</span>
      case 'date':
        return <span className="cell-muted">{raw ? formatDate(String(raw)) : ''}</span>
      case 'badge': {
        const text = asText(raw)
        if (!text) return <span className="cell-no">-</span>
        const tone = col.tone_map[text] || col.tone_map[text.toLowerCase()] || 'info'
        return <span className={`pill pill-${tone}`}>{text}</span>
      }
      case 'list': {
        const values = Array.isArray(raw)
          ? raw.map(asText)
          : asText(raw)
              .split(/[,;]\s*/)
              .filter(Boolean)
        if (!values.length) return <span className="cell-no">-</span>
        return (
          <span className="cell-pills">
            {values.slice(0, 6).map((v, i) => (
              <span key={`${v}-${i}`} className="pill pill-muted">
                {v}
              </span>
            ))}
            {values.length > 6 && <span className="cell-muted">+{values.length - 6}</span>}
          </span>
        )
      }
      default:
        return <span title={asText(raw)}>{asText(raw)}</span>
    }
  }

  function renderDepsCell(item: ResourceItem) {
    if (item.deps_count === null || item.deps_count === undefined) {
      return (
        <span className="cell-muted" title="Dependencies have not been checked for this row">
          not checked
        </span>
      )
    }
    if (item.deps_count === 0) {
      return <span className="pill pill-ok">unused</span>
    }
    return (
      <button type="button" className="deps-toggle" onClick={() => toggleExpanded(item.key)}>
        <span className="pill pill-warn">{item.deps_count} in use</span>
        <span className={`sidebar-caret ${expanded.has(item.key) ? 'open' : ''}`}>&#9656;</span>
      </button>
    )
  }

  const optionalColumns = columns.filter((c) => c.optional || hiddenCols.has(c.key))
  const colSpan = 1 + (showScope ? 1 : 0) + 1 + dataColumns.length + (hasDeps ? 1 : 0)

  return (
    <div className="resource-table-wrap">
      <div className="resource-table-toolbar">
        <input
          type="search"
          className="resource-filter"
          placeholder={`Filter ${items.length} row${items.length === 1 ? '' : 's'}...`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="resource-select-buttons">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={selectAllVisible}
            disabled={selectableKeys.length === 0}
          >
            Select all
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={unselectAllVisible}
            disabled={selected.size === 0}
          >
            Unselect all
          </button>
          {optionalColumns.length > 0 && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setShowColumnPicker((v) => !v)}
            >
              Columns
            </button>
          )}
        </div>
        <span className="resource-count">
          {visible.length === items.length
            ? `${items.length} row${items.length === 1 ? '' : 's'}`
            : `${visible.length} of ${items.length} rows`}
          {selected.size > 0 && ` - ${selected.size} selected`}
        </span>
      </div>

      {showColumnPicker && optionalColumns.length > 0 && (
        <div className="column-picker">
          {columns
            .filter((c) => c.kind !== 'deps')
            .map((c) => (
              <label key={c.key} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={!hiddenCols.has(c.key)}
                  onChange={() =>
                    setHiddenCols((prev) => {
                      const next = new Set(prev)
                      if (next.has(c.key)) next.delete(c.key)
                      else next.add(c.key)
                      return next
                    })
                  }
                />
                {c.label}
              </label>
            ))}
        </div>
      )}

      <div className="resource-table-scroll">
        <table className="resource-table">
          <thead>
            <tr>
              <th className="col-check">
                <input
                  type="checkbox"
                  aria-label="Select all rows in view"
                  checked={allVisibleSelected}
                  disabled={selectableKeys.length === 0}
                  onChange={() => (allVisibleSelected ? unselectAllVisible() : selectAllVisible())}
                />
              </th>
              {showScope && (
                <th className="sortable" onClick={() => toggleSort(SCOPE_COL)}>
                  System
                  {sortKey === SCOPE_COL && (
                    <span className="sort-arrow">{sortDir === 'asc' ? ' ▲' : ' ▼'}</span>
                  )}
                </th>
              )}
              <th className="sortable" onClick={() => toggleSort(KEY_COL)}>
                {keyLabel}
                {sortKey === KEY_COL && <span className="sort-arrow">{sortDir === 'asc' ? ' ▲' : ' ▼'}</span>}
              </th>
              {dataColumns.map((col) => (
                <th
                  key={col.key}
                  className="sortable"
                  style={col.width ? { width: col.width } : undefined}
                  title={col.help || undefined}
                  onClick={() => toggleSort(col.key)}
                >
                  {col.label}
                  {sortKey === col.key && (
                    <span className="sort-arrow">{sortDir === 'asc' ? ' ▲' : ' ▼'}</span>
                  )}
                </th>
              ))}
              {hasDeps && (
                <th className="sortable" onClick={() => toggleSort(DEPS_COL)}>
                  {depsColumn?.label || depsLabel}
                  {sortKey === DEPS_COL && (
                    <span className="sort-arrow">{sortDir === 'asc' ? ' ▲' : ' ▼'}</span>
                  )}
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={colSpan} className="resource-empty">
                  {items.length === 0 ? emptyMessage : 'No row matches the filter.'}
                </td>
              </tr>
            )}
            {visible.map((item) => {
              const isProtected = protectedSet.has(item.key)
              const isSelected = selected.has(item.key)
              return [
                <tr
                  key={item.key}
                  className={`${isSelected ? 'row-selected' : ''} ${isProtected ? 'row-protected' : ''}`}
                >
                  <td className="col-check">
                    <input
                      type="checkbox"
                      aria-label={`Select ${item.key}`}
                      checked={isSelected}
                      disabled={isProtected}
                      title={isProtected ? 'System object; cannot be changed' : undefined}
                      onChange={() => toggleRow(item.key)}
                    />
                  </td>
                  {showScope && <td className="cell-muted">{item.scope}</td>}
                  <td className="col-key">
                    {item.key}
                    {isProtected && <span className="pill pill-muted">system</span>}
                  </td>
                  {dataColumns.map((col) => (
                    <td key={col.key}>{renderCell(item, col)}</td>
                  ))}
                  {hasDeps && <td className="col-deps">{renderDepsCell(item)}</td>}
                </tr>,
                hasDeps && expanded.has(item.key) && (item.deps?.length ?? 0) > 0 ? (
                  <tr key={`${item.key}-deps`} className="row-deps-detail">
                    <td colSpan={colSpan}>
                      <div className="deps-detail">
                        <strong>{item.key}</strong> is used by:
                        <ul>
                          {item.deps?.map((dep, i) => (
                            <li key={`${dep.name}-${i}`}>
                              {dep.name}
                              {dep.type && <span className="pill pill-muted">{dep.type}</span>}
                              {dep.detail && <span className="cell-muted"> {dep.detail}</span>}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </td>
                  </tr>
                ) : null,
              ]
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
