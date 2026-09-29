import { useScripts } from '../App'

export default function Landing() {
  const { categories, loading } = useScripts()

  return (
    <div className="page landing-page">
      <div className="landing-hero">
        <img src="/slab42.jpg" alt="slab42 logo" className="landing-logo" />
        <div>
          <h1>Welcome to slab42 UC-Automations</h1>
          <p>
            This is the web front end for the <code>main.py</code> script launcher. Pick a
            platform in the left menu, pick a script, and run it right here in the browser.
            Every prompt the script would normally ask on the command line shows up as a form
            field, so there is no need to drop to a shell.
          </p>
        </div>
      </div>

      {loading && <p>Loading categories...</p>}

      <div className="landing-cards">
        {categories.map((cat) => (
          <div key={cat.dir} className="landing-card">
            <h3>{cat.label}</h3>
            <p>{cat.description}</p>
            <div className="landing-card-count">
              {cat.scripts.length} script{cat.scripts.length === 1 ? '' : 's'}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
