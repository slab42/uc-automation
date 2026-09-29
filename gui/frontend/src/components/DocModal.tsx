import { useEffect } from 'react'
import type { ScriptInfo } from '../types'

interface Props {
  script: ScriptInfo
  onClose: () => void
}

export default function DocModal({ script, onClose }: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="doc-modal-backdrop" onClick={onClose}>
      <div className="doc-modal" onClick={(e) => e.stopPropagation()}>
        <button className="doc-modal-close" onClick={onClose} aria-label="Close">
          ✕
        </button>
        <h2>{script.title}</h2>
        <div className="doc-modal-rel">{script.rel}</div>
        <pre className="doc-modal-body">
          {script.description ?? 'No description in this script.'}
        </pre>
      </div>
    </div>
  )
}
