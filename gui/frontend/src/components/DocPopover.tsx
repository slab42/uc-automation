import { useEffect, useRef, useState } from 'react'
import type { ScriptInfo } from '../types'

interface Props {
  script: ScriptInfo
  anchorRect: DOMRect
  onOpenFull: () => void
  onMouseEnter: () => void
  onMouseLeave: () => void
}

const MAX_WIDTH = 520
const MAX_HEIGHT_VH = 0.6

export default function DocPopover({
  script,
  anchorRect,
  onOpenFull,
  onMouseEnter,
  onMouseLeave,
}: Props) {
  const popRef = useRef<HTMLDivElement>(null)
  const [style, setStyle] = useState<React.CSSProperties>({})

  useEffect(() => {
    const viewportW = window.innerWidth
    const viewportH = window.innerHeight
    const maxHeight = viewportH * MAX_HEIGHT_VH
    let left = anchorRect.right + 8
    let top = anchorRect.top
    if (left + MAX_WIDTH > viewportW) {
      left = Math.max(8, viewportW - MAX_WIDTH - 8)
    }
    if (top + maxHeight > viewportH) {
      top = Math.max(8, viewportH - maxHeight - 8)
    }
    setStyle({
      left,
      top,
      maxWidth: MAX_WIDTH,
      maxHeight,
    })
  }, [anchorRect])

  return (
    <div
      ref={popRef}
      className="doc-popover"
      style={style}
      onClick={onOpenFull}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      role="button"
      tabIndex={0}
    >
      <div className="doc-popover-header">{script.title} (click to expand)</div>
      <div className="doc-popover-body">
        <pre>{script.description ?? 'No description in this script.'}</pre>
        <div className="doc-popover-fade" />
      </div>
    </div>
  )
}
