'use client'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

const EXAMPLES = [
  'Can you write me a README?',
  'Add type hints to all functions and improve variable naming',
  'Write pytest tests for all public functions with edge cases',
  'Add docstrings to every function and update the README',
  'Explain the project structure and how the main pieces fit together',
]

type RecentSession = {
  session_id: string
  workspace: string
  mode: string
  updated_at: string
  turn_count: number
  title: string
  starred: boolean
}

export default function Home() {
  const router = useRouter()
  const backendUrl = useMemo(() => (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000').replace(/\/+$/, ''), [])
  const [goal, setGoal] = useState('')
  const [workspace, setWorkspace] = useState('')
  const [error, setError] = useState('')
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([])
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [renameSessionId, setRenameSessionId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [isMobile, setIsMobile] = useState(false)
  const menuRootRef = useRef<HTMLDivElement>(null)

  const sortedSessions = useMemo(
    () =>
      [...recentSessions].sort((a, b) => {
        if (a.starred !== b.starred) return Number(b.starred) - Number(a.starred)
        return new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
      }),
    [recentSessions],
  )
  const starredSessions = sortedSessions.filter(session => session.starred)
  const unstarredSessions = sortedSessions.filter(session => !session.starred)

  useEffect(() => {
    let cancelled = false

    async function loadSessions() {
      try {
        const res = await fetch(`${backendUrl}/api/sessions`)
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled) setRecentSessions(data.sessions || [])
      } catch {
        // best effort only
      }
    }

    void loadSessions()
    return () => {
      cancelled = true
    }
  }, [backendUrl])

  useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < 860)
    }

    handleResize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [])

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!menuRootRef.current) return
      if (!menuRootRef.current.contains(event.target as Node)) {
        setOpenMenuId(null)
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpenMenuId(null)
        setRenameSessionId(null)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [])

  function start() {
    if (!workspace.trim()) { setError('Please enter the path to your project'); return }
    setError('')
    const params = new URLSearchParams({ workspace: workspace.trim() })
    if (goal.trim()) params.set('goal', goal.trim())
    router.push(`/session?${params}`)
  }

  async function toggleStar(sessionId: string, starred: boolean) {
    try {
      const res = await fetch(`${backendUrl}/api/sessions/${sessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ starred: !starred }),
      })
      if (!res.ok) throw new Error('Unable to update session')
      setRecentSessions(previous =>
        previous.map(session => (session.session_id === sessionId ? { ...session, starred: !starred } : session)),
      )
      setOpenMenuId(null)
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : 'Unable to update session')
    }
  }

  async function deleteSession(sessionId: string) {
    try {
      const res = await fetch(`${backendUrl}/api/sessions/${sessionId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Unable to delete session')
      setRecentSessions(previous => previous.filter(session => session.session_id !== sessionId))
      setOpenMenuId(null)
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Unable to delete session')
    }
  }

  async function renameSession() {
    if (!renameSessionId) return
    try {
      const res = await fetch(`${backendUrl}/api/sessions/${renameSessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: renameValue }),
      })
      if (!res.ok) throw new Error('Unable to rename session')
      setRecentSessions(previous =>
        previous.map(session => (session.session_id === renameSessionId ? { ...session, title: renameValue.trim() || session.title } : session)),
      )
      setRenameSessionId(null)
      setRenameValue('')
      setOpenMenuId(null)
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : 'Unable to rename session')
    }
  }

  function openRename(session: RecentSession) {
    setRenameSessionId(session.session_id)
    setRenameValue(session.title)
    setOpenMenuId(null)
  }

  function renderSessionSection(title: string, sessions: RecentSession[]) {
    if (sessions.length === 0) return null
    return (
      <div style={{ display: 'grid', gap: 10 }}>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
          {title}
        </p>
        {sessions.map(session => (
          <div
            key={session.session_id}
            style={{ position: 'relative', textAlign: 'left', background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 16, padding: isMobile ? '12px 14px' : '14px 16px', boxShadow: 'var(--shadow-md)' }}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
              <button
                onClick={() => router.push(`/session?session=${session.session_id}`)}
                style={{ flex: 1, textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', padding: 0, minWidth: 0 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  {session.starred && (
                    <span style={{ color: 'var(--accent)', display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="m12 17.3-6.18 3.73 1.64-7.03L2 9.27l7.19-.61L12 2l2.81 6.66 7.19.61-5.46 4.73 1.64 7.03z" /></svg>
                    </span>
                  )}
                  <p style={{ fontSize: 14, color: 'var(--text-primary)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{session.title || 'Untitled session'}</p>
                </div>
                <p style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', marginTop: 6, wordBreak: 'break-all' }}>{session.workspace}</p>
                <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>Reopen chat</p>
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, position: 'relative', flexShrink: 0 }}>
                {!isMobile && <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{session.turn_count} turn{session.turn_count === 1 ? '' : 's'}</span>}
                <button
                  onClick={() => setOpenMenuId(current => (current === session.session_id ? null : session.session_id))}
                  style={{ width: 28, height: 28, borderRadius: 999, border: 'none', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0 }}
                  aria-label="Session options"
                  title="Session options"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <circle cx="5" cy="12" r="2" />
                    <circle cx="12" cy="12" r="2" />
                    <circle cx="19" cy="12" r="2" />
                  </svg>
                </button>
                {openMenuId === session.session_id && (
                  <div style={{ position: 'absolute', top: 34, right: 0, width: 188, borderRadius: 18, border: '1px solid var(--border)', background: 'var(--bg-surface)', boxShadow: 'var(--shadow-lg)', padding: 8, zIndex: 10 }}>
                    <button
                      onClick={() => toggleStar(session.session_id, session.starred)}
                      style={{ width: '100%', textAlign: 'left', border: 'none', background: 'none', padding: '10px 12px', borderRadius: 12, cursor: 'pointer', color: 'var(--text-primary)', fontSize: 14, display: 'flex', alignItems: 'center', gap: 10 }}
                    >
                      <span style={{ color: 'var(--accent)' }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill={session.starred ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
                          <path d="m12 17.3-6.18 3.73 1.64-7.03L2 9.27l7.19-.61L12 2l2.81 6.66 7.19.61-5.46 4.73 1.64 7.03z" />
                        </svg>
                      </span>
                      {session.starred ? 'Unstar' : 'Star'}
                    </button>
                    <button
                      onClick={() => openRename(session)}
                      style={{ width: '100%', textAlign: 'left', border: 'none', background: 'none', padding: '10px 12px', borderRadius: 12, cursor: 'pointer', color: 'var(--text-primary)', fontSize: 14, display: 'flex', alignItems: 'center', gap: 10 }}
                    >
                      <span>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M12 20h9" />
                          <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
                        </svg>
                      </span>
                      Rename
                    </button>
                    <div style={{ height: 1, background: 'var(--border)', margin: '4px 6px' }} />
                    <button
                      onClick={() => deleteSession(session.session_id)}
                      style={{ width: '100%', textAlign: 'left', border: 'none', background: 'none', padding: '10px 12px', borderRadius: 12, cursor: 'pointer', color: 'var(--red)', fontSize: 14, display: 'flex', alignItems: 'center', gap: 10 }}
                    >
                      <span>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M3 6h18" />
                          <path d="M8 6V4h8v2" />
                          <path d="M19 6l-1 14H6L5 6" />
                        </svg>
                      </span>
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
            {isMobile && <p style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--accent)', marginTop: 8 }}>{session.turn_count} turn{session.turn_count === 1 ? '' : 's'}</p>}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: recentSessions.length > 0 ? 'flex-start' : 'center', padding: isMobile ? '28px 16px 40px' : '40px 24px' }}>

      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: 'var(--accent-dim)', border: '1px solid var(--border-bright)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-mono)', fontSize: 16, color: 'var(--accent)' }}>
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
      <div style={{ width: '100%', maxWidth: 600, background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 18, padding: 28, display: 'flex', flexDirection: 'column', gap: 22, boxShadow: 'var(--shadow-lg)', backdropFilter: 'blur(10px)' }}>

        {/* Goal input */}
        <div>
          <label style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', display: 'block', marginBottom: 8 }}>
            First message
          </label>
          <textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            placeholder="Optional: ask for a README, refactor, tests, docs..."
            rows={3}
            style={{
              width: '100%', background: 'var(--bg-raised)', border: '1px solid var(--border)',
              borderRadius: 8, padding: '10px 12px', color: 'var(--text-primary)',
              fontFamily: 'var(--font-sans)', fontSize: 14, resize: 'vertical',
              outline: 'none', lineHeight: 1.6,
            }}
            onFocus={e => e.target.style.borderColor = 'var(--accent)'}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
          {/* Example chips */}
          <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {EXAMPLES.map(ex => (
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
            onFocus={e => e.target.style.borderColor = 'var(--accent)'}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5 }}>
            Absolute path to the project folder on your machine
          </p>
        </div>

        {error && <p style={{ fontSize: 12, color: 'var(--red)', background: 'var(--red-dim)', padding: '8px 12px', borderRadius: 6 }}>{error}</p>}

        <button onClick={start} style={{
          padding: '11px', borderRadius: 8, background: 'var(--accent)',
          border: 'none', color: 'var(--accent-contrast)', fontFamily: 'var(--font-mono)',
          fontSize: 13, fontWeight: 500, cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          boxShadow: 'var(--shadow-md)',
        }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="5 3 19 12 5 21 5 3" /></svg>
          Open workspace
        </button>
      </div>

      <p style={{ marginTop: 20, fontSize: 11, color: 'var(--text-muted)', textAlign: 'center' }}>
        Powered by Groq · LLaMA 3.3 70B · Real file system access
      </p>

      {sortedSessions.length > 0 && (
        <div ref={menuRootRef} style={{ width: '100%', maxWidth: 760, marginTop: 28 }}>
          <div style={{ display: 'grid', gap: 18 }}>
            {renderSessionSection('Starred', starredSessions)}
            {renderSessionSection(starredSessions.length > 0 ? 'Recent' : 'Recent sessions', unstarredSessions)}
          </div>
        </div>
      )}

      {renameSessionId && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.28)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, zIndex: 30 }}>
          <div style={{ width: '100%', maxWidth: 420, borderRadius: 22, background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: 'var(--shadow-lg)', padding: 18 }}>
            <p style={{ fontSize: 16, color: 'var(--text-primary)', fontWeight: 500 }}>Rename session</p>
            <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>Give this chat a clearer label for your history.</p>
            <input
              value={renameValue}
              onChange={event => setRenameValue(event.target.value)}
              placeholder="Session name"
              autoFocus
              style={{ width: '100%', marginTop: 14, background: 'var(--bg-raised)', border: '1px solid var(--border)', borderRadius: 12, padding: '11px 12px', color: 'var(--text-primary)', fontSize: 14, outline: 'none' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 16 }}>
              <button onClick={() => setRenameSessionId(null)} style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg-surface)', color: 'var(--text-primary)', cursor: 'pointer' }}>
                Cancel
              </button>
              <button onClick={renameSession} style={{ padding: '10px 12px', borderRadius: 10, border: 'none', background: 'var(--accent)', color: 'var(--accent-contrast)', cursor: 'pointer' }}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
