import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getResourceCatalog } from '../api'
import ResourcePanel from '../components/ResourcePanel'
import type { ResourceCatalog } from '../types'

/**
 * Browse every registered resource, whether or not a script page uses it.
 *
 * The script pages are task-shaped ("delete softkey templates"); this page
 * is inventory-shaped, and it is also where a resource that no script page
 * references is reachable at all. Same panel either way.
 */
export default function ResourcesPage() {
  const { resourceId } = useParams<{ resourceId?: string }>()
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<ResourceCatalog | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getResourceCatalog()
      .then(setCatalog)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const all = useMemo(
    () => (catalog?.services ?? []).flatMap((s) => s.resources),
    [catalog],
  )
  const current = resourceId || all[0]?.id || ''

  return (
    <div className="page">
      <div className="script-header">
        <h1>Resources</h1>
        <div className="script-meta">
          <span className="script-rel">{all.length} registered</span>
        </div>
      </div>

      <p className="settings-note">
        Every kind of object the GUI can list, cache and act on. The script pages show the same
        panels, arranged per task.
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="resource-chooser">
        {(catalog?.services ?? []).map((svc) => (
          <div key={svc.service} className="resource-chooser-group">
            <h3>
              {svc.service}
              <span className="cell-muted">
                {svc.targets.filter((t) => t.ready).length}/{svc.targets.length} ready
              </span>
            </h3>
            <div className="resource-chooser-items">
              {svc.resources.map((res) => (
                <button
                  key={res.id}
                  className={`resource-chip ${res.id === current ? 'active' : ''}`}
                  onClick={() => navigate(`/resources/${res.id}`)}
                >
                  {res.label}
                  <span className="cell-muted">{res.cached_items}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {current && <ResourcePanel key={current} resourceId={current} />}
    </div>
  )
}
