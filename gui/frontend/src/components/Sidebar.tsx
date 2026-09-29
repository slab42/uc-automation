import { useRef, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useScripts } from '../App'
import type { ScriptInfo } from '../types'
import DocPopover from './DocPopover'
import DocModal from './DocModal'

const CLOSE_DELAY = 150

export default function Sidebar() {
  const { categories, error } = useScripts()
  const [openCategories, setOpenCategories] = useState<Set<string>>(new Set())
  const [hovered, setHovered] = useState<{ script: ScriptInfo; rect: DOMRect } | null>(null)
  const [modalScript, setModalScript] = useState<ScriptInfo | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  function toggleCategory(dir: string) {
    setOpenCategories((prev) => {
      const next = new Set(prev)
      if (next.has(dir)) next.delete(dir)
      else next.add(dir)
      return next
    })
  }

  function scheduleClose() {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => {
      setHovered(null)
    }, CLOSE_DELAY)
  }

  function cancelClose() {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }

  function onScriptEnter(script: ScriptInfo, e: React.MouseEvent<HTMLElement>) {
    cancelClose()
    const rect = e.currentTarget.getBoundingClientRect()
    setHovered({ script, rect })
  }

  return (
    <>
      <aside className="sidebar">
        <Link to="/" className="sidebar-brand">
          <img src="/slab42.jpg" alt="slab42 logo" className="sidebar-logo" />
          <span className="sidebar-brand-text">slab42 UC-Automations</span>
        </Link>

        {error && <div className="sidebar-error">API unreachable</div>}

        <nav className="sidebar-nav">
          {categories.map((cat) => {
            const isOpen = openCategories.has(cat.dir)
            return (
              <div key={cat.dir} className="sidebar-category">
                <button
                  className="sidebar-category-btn"
                  onClick={() => toggleCategory(cat.dir)}
                  aria-expanded={isOpen}
                >
                  <span className={`sidebar-caret ${isOpen ? 'open' : ''}`}>▸</span>
                  {cat.label}
                </button>
                {isOpen && (
                  <div className="sidebar-subitems">
                    {cat.scripts.map((script) => (
                      <NavLink
                        key={script.rel}
                        to={`/scripts/${script.rel}`}
                        className={({ isActive }) =>
                          `sidebar-subitem ${isActive ? 'active' : ''}`
                        }
                        onMouseEnter={(e) => onScriptEnter(script, e)}
                        onMouseLeave={scheduleClose}
                      >
                        <span className="sidebar-subitem-title">{script.title}</span>
                        {script.takes_args && <span className="args-badge">args</span>}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </nav>

        <div className="sidebar-footer">
          <NavLink
            to="/settings"
            className={({ isActive }) => `sidebar-settings ${isActive ? 'active' : ''}`}
          >
            <span className="sidebar-gear" aria-hidden="true">
              ⚙
            </span>
            Settings
          </NavLink>
        </div>
      </aside>

      {hovered && !modalScript && (
        <DocPopover
          script={hovered.script}
          anchorRect={hovered.rect}
          onOpenFull={() => {
            setModalScript(hovered.script)
            setHovered(null)
          }}
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
        />
      )}

      {modalScript && <DocModal script={modalScript} onClose={() => setModalScript(null)} />}
    </>
  )
}
