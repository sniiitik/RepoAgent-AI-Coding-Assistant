'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'

const MODES = [
  { id: 'refactor', label: 'Refactor', desc: 'Improve code quality, naming, and structure', icon: '⟳' },
  { id: 'test', label: 'Write tests', desc: 'Generate comprehensive test suites', icon: '✓' },
  { id: 'document', label: 'Document', desc: 'Add docstrings, comments, and README', icon: '≡' },
]

const EXAMPLES = [
  'Add type hints to all functions and improve variable naming',
  'Write pytest tests for all public functions with edge cases',
  'Add docstrings to every function and update the README',
  'Refactor duplicate code into reusable helper functions',
  'Convert synchronous functions to async where appropriate',
]

export default function Home() {
  const router = useRouter()
  const [mode, setMode] = useState('refactor')
  const [goal, setGoal] = useState('')
  const [workspace, setWorkspace] = useState('')
  const [error, setError] = useState('')

  function start() {
    if (!goal.trim()) { setError('Please describe what you want the agent to do'); return }
    if (!workspace.trim()) { setError('Please enter the path to your project'); return }
    setError('')
    const params = new URLSearchParams({ goal: goal.trim(), mode, workspace: workspace.trim() })
    router.push(`/session?${params}`)
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 24px' }}>

      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: 'var(--accent-dim)', border: '1px solid rgba(88,166,255,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-mono)', fontSize: 16, color: 'var(--accent)' }}>
            {'</>'}
          </div>
          <h1 style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 500, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
            RepoAgent
          </h1>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
          Autonomous AI agent that reads, understands, and improves your code
        </p>
      </div>

      {/* Card */}
      <div style={{ width: '100%', maxWidth: 600, background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 28, display: 'flex', flexDirection: 'column', gap: 22 }}>

        {/* Mode selector */}
        <div>
          <label style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', display: 'block', marginBottom: 10 }}>
            Mode
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {MODES.map(m => (
              <button key={m.id} onClick={() => setMode(m.id)} style={{
                padding: '10px 12px', borderRadius: 8, textAlign: 'left',
                background: mode === m.id ? 'var(--accent-dim)' : 'var(--bg-raised)',
                border: `1px solid ${mode === m.id ? 'rgba(88,166,255,0.4)' : 'var(--border)'}`,
                cursor: 'pointer', transition: 'all 0.15s',
              }}>
                <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: mode === m.id ? 'var(--accent)' : 'var(--text-muted)', marginBottom: 3 }}>{m.label}</div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.4 }}>{m.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Goal input */}
        <div>
          <label style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', display: 'block', marginBottom: 8 }}>
            Goal
          </label>
          <textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            placeholder="Describe what you want the agent to do..."
            rows={3}
            style={{
              width: '100%', background: 'var(--bg-raised)', border: '1px solid var(--border)',
              borderRadius: 8, padding: '10px 12px', color: 'var(--text-primary)',
              fontFamily: 'var(--font-sans)', fontSize: 14, resize: 'vertical',
              outline: 'none', lineHeight: 1.6,
            }}
            onFocus={e => e.target.style.borderColor = 'rgba(88,166,255,0.5)'}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
          {/* Example chips */}
          <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {EXAMPLES.filter((_, i) => {
              if (mode === 'refactor') return i === 0 || i === 3 || i === 4
              if (mode === 'test') return i === 1
              return i === 2
            }).map(ex => (
              <button key={ex} onClick={() => setGoal(ex)} style={{
                fontSize: 11, padding: '3px 10px', borderRadius: 20,
                background: 'var(--bg-raised)', border: '1px solid var(--border)',
                color: 'var(--text-secondary)', cursor: 'pointer',
              }}>
                {ex.length > 50 ? ex.slice(0, 50) + '…' : ex}
              </button>
            ))}
          </div>
        </div>

        {/* Workspace path */}
        <div>
          <label style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', display: 'block', marginBottom: 8 }}>
            Project path
          </label>
          <input
            value={workspace}
            onChange={e => setWorkspace(e.target.value)}
            placeholder="/Users/you/projects/my-app"
            style={{
              width: '100%', background: 'var(--bg-raised)', border: '1px solid var(--border)',
              borderRadius: 8, padding: '9px 12px', color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)', fontSize: 13, outline: 'none',
            }}
            onFocus={e => e.target.style.borderColor = 'rgba(88,166,255,0.5)'}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5 }}>
            Absolute path to the project folder on your machine
          </p>
        </div>

        {error && <p style={{ fontSize: 12, color: 'var(--red)', background: 'var(--red-dim)', padding: '8px 12px', borderRadius: 6 }}>{error}</p>}

        <button onClick={start} style={{
          padding: '11px', borderRadius: 8, background: 'var(--accent)',
          border: 'none', color: '#0d1117', fontFamily: 'var(--font-mono)',
          fontSize: 13, fontWeight: 500, cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="5 3 19 12 5 21 5 3" /></svg>
          Run agent
        </button>
      </div>

      <p style={{ marginTop: 20, fontSize: 11, color: 'var(--text-muted)', textAlign: 'center' }}>
        Powered by Groq · LLaMA 3.3 70B · Real file system access
      </p>
    </div>
  )
}