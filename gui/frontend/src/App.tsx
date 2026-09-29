import { createContext, useContext, useEffect, useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { getScripts } from './api'
import Sidebar from './components/Sidebar'
import Landing from './pages/Landing'
import ScriptPage from './pages/ScriptPage'
import SettingsPage from './pages/SettingsPage'
import type { CategoryInfo } from './types'

export interface ScriptsContextValue {
  categories: CategoryInfo[]
  loading: boolean
  error: string | null
}

export const ScriptsContext = createContext<ScriptsContextValue>({
  categories: [],
  loading: true,
  error: null,
})

export function useScripts(): ScriptsContextValue {
  return useContext(ScriptsContext)
}

export default function App() {
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getScripts()
      .then((res) => {
        if (cancelled) return
        setCategories(res.categories)
        setLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const value: ScriptsContextValue = { categories, loading, error }

  return (
    <ScriptsContext.Provider value={value}>
      <div className="app-shell">
        <Sidebar />
        <main className="main-area">
          {error && (
            <div className="error-banner">
              Backend not reachable at /api. Start it with{' '}
              <code>python3 main.py --gui</code>.
            </div>
          )}
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/scripts/*" element={<ScriptPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </ScriptsContext.Provider>
  )
}
