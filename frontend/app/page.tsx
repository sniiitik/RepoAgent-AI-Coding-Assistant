'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

const EXAMPLES = [
  'Explain the architecture',
  'Write a README for this repo',
  'Add tests for the backend',
  'Find cleanup opportunities',
  'Summarize how the app works',
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
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<RecentSession | null>(null)
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
        setDeleteSessionTarget(null)
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
    const normalizedWorkspace = workspace.trim()
    if (!normalizedWorkspace) {
      setError('Please enter the path to your project')
      return
    }
    setError('')
    const existingSession = sortedSessions.find(session => session.workspace === normalizedWorkspace)
    const params = new URLSearchParams(existingSession ? { session: existingSession.session_id } : { workspace: normalizedWorkspace })
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

  function confirmDelete(session: RecentSession) {
    setDeleteSessionTarget(session)
    setOpenMenuId(null)
  }

  function projectName(path: string) {
    const parts = path.split('/').filter(Boolean)
    return parts[parts.length - 1] || path
  }

  function renderSessionSection(title: string, sessions: RecentSession[]) {
    if (sessions.length === 0) return null
    return (
      <div style={{ display: 'grid', gap: 10 }}>
        <p style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          {title}
        </p>
        {sessions.map(session => (
          <div
            key={session.session_id}
            style={{
              position: 'relative',
              border: '1px solid var(--border)',
              borderRadius: 14,
              background: 'linear-gradient(180deg, var(--bg-surface) 0%, color-mix(in srgb, var(--bg-surface) 84%, var(--bg-raised) 16%) 100%)',
              boxShadow: 'var(--shadow-md)',
              padding: isMobile ? '11px 12px' : '13px 14px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <button
                onClick={() => router.push(`/session?session=${session.session_id}`)}
                style={{ flex: 1, minWidth: 0, background: 'none', border: 'none', textAlign: 'left', cursor: 'pointer', padding: 0 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  {session.starred && <span style={{ color: 'var(--accent)', fontSize: 12, flexShrink: 0 }}>*</span>}
                  <p style={{ fontSize: 15, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {session.title || 'untitled'}
                  </p>
                </div>
                <p style={{ marginTop: 6, fontSize: 12, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                  {projectName(session.workspace)}
                </p>
                <p style={{ marginTop: 5, fontSize: 11, color: 'var(--text-muted)' }}>
                  reopen chat
                </p>
              </button>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, position: 'relative', flexShrink: 0 }}>
                {!isMobile && (
                  <span style={{ fontSize: 11, color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>
                    {session.turn_count} turn{session.turn_count === 1 ? '' : 's'}
                  </span>
                )}
                <button
                  onClick={() => setOpenMenuId(current => (current === session.session_id ? null : session.session_id))}
                  aria-label="Session options"
                  title="Session options"
                  style={{ border: 'none', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', padding: 0, width: 24, height: 24 }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <circle cx="5" cy="12" r="2" />
                    <circle cx="12" cy="12" r="2" />
                    <circle cx="19" cy="12" r="2" />
                  </svg>
                </button>

                {openMenuId === session.session_id && (
                  <div style={{ position: 'absolute', bottom: 30, right: 0, width: 188, borderRadius: 14, border: '1px solid var(--border)', background: 'var(--bg-surface)', boxShadow: 'var(--shadow-lg)', padding: 6, zIndex: 10 }}>
                    <button
                      onClick={() => toggleStar(session.session_id, session.starred)}
                      style={{ width: '100%', textAlign: 'left', border: 'none', background: 'transparent', color: 'var(--text-primary)', padding: '10px 11px', borderRadius: 10, cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 13 }}
                    >
                      {session.starred ? 'unstar' : 'star'}
                    </button>
                    <button
                      onClick={() => openRename(session)}
                      style={{ width: '100%', textAlign: 'left', border: 'none', background: 'transparent', color: 'var(--text-primary)', padding: '10px 11px', borderRadius: 10, cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 13 }}
                    >
                      rename
                    </button>
                    <div style={{ height: 1, background: 'var(--border)', margin: '4px 6px' }} />
                    <button
                      onClick={() => confirmDelete(session)}
                      style={{ width: '100%', textAlign: 'left', border: 'none', background: 'transparent', color: 'var(--red)', padding: '10px 11px', borderRadius: 10, cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 13 }}
                    >
                      delete
                    </button>
                  </div>
                )}
              </div>
            </div>
            {isMobile && (
              <p style={{ marginTop: 8, fontSize: 11, color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>
                {session.turn_count} turn{session.turn_count === 1 ? '' : 's'}
              </p>
            )}
          </div>
        ))}
      </div>
    )
  }

  const canStart = workspace.trim().length > 0

  return (
    <div style={{ minHeight: '100vh', padding: isMobile ? '24px 14px 40px' : '36px 24px 56px', display: 'flex', alignItems: sortedSessions.length > 0 ? 'flex-start' : 'center' }}>
      <div style={{ width: '100%', maxWidth: 920, margin: '0 auto' }}>
        <div
          style={{
            border: '1px solid var(--border)',
            borderRadius: 16,
            background: 'var(--bg-surface)',
            boxShadow: 'var(--shadow-md)',
            overflow: 'hidden',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--bg-raised)' }}>
            <span style={{ width: 10, height: 10, borderRadius: 999, background: 'var(--red)', opacity: 0.8 }} />
            <span style={{ width: 10, height: 10, borderRadius: 999, background: 'var(--orange)', opacity: 0.8 }} />
            <span style={{ width: 10, height: 10, borderRadius: 999, background: 'var(--green)', opacity: 0.8 }} />
            <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              CodeWeave
            </span>
          </div>

          <div style={{ padding: isMobile ? '20px 16px 16px' : '26px 28px 22px' }}>
            <p style={{ fontSize: 12, color: 'var(--accent)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              $ codeweave start
            </p>
            <h1 style={{ marginTop: 14, fontSize: isMobile ? 32 : 44, lineHeight: 1.04, letterSpacing: '-0.05em', color: 'var(--text-primary)', fontWeight: 500, maxWidth: 620 }}>
              talk to your codebase.
            </h1>
            <p style={{ marginTop: 10, fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.75, maxWidth: 620 }}>
              Open a local repo, ask what it does, request a change, and keep the same session alive.
            </p>

            <div style={{ marginTop: 20, display: 'grid', gap: 12 }}>
              <div>
                <label style={{ display: 'block', marginBottom: 8, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  project path
                </label>
                <input
                  value={workspace}
                  onChange={event => setWorkspace(event.target.value)}
                  placeholder="/Users/you/projects/my-app"
                  style={{
                    width: '100%',
                    border: '1px solid var(--border)',
                    borderRadius: 12,
                    background: 'var(--bg-raised)',
                    color: 'var(--text-primary)',
                    padding: '11px 12px',
                    fontSize: 13,
                    outline: 'none',
                    fontFamily: 'var(--font-mono)',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: 8, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  first message
                </label>
                <textarea
                  value={goal}
                  onChange={event => setGoal(event.target.value)}
                  placeholder="optional: explain the architecture, write a README, add tests..."
                  rows={3}
                  style={{
                    width: '100%',
                    border: '1px solid var(--border)',
                    borderRadius: 12,
                    background: 'var(--bg-raised)',
                    color: 'var(--text-primary)',
                    padding: '12px 13px',
                    fontSize: 14,
                    lineHeight: 1.6,
                    outline: 'none',
                    resize: 'vertical',
                    fontFamily: 'var(--font-sans)',
                  }}
                />
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {EXAMPLES.map(example => (
                  <button
                    key={example}
                    onClick={() => setGoal(example)}
                    style={{ border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', borderRadius: 999, padding: '6px 10px', cursor: 'pointer', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                  >
                    {example}
                  </button>
                ))}
              </div>

              {error && (
                <div style={{ padding: '10px 12px', borderRadius: 10, background: 'var(--red-dim)', color: 'var(--red)', fontSize: 12 }}>
                  {error}
                </div>
              )}

              <div style={{ display: 'flex', alignItems: isMobile ? 'stretch' : 'center', justifyContent: 'space-between', gap: 10, flexDirection: isMobile ? 'column' : 'row' }}>
                <p style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.7 }}>
                  Writes and commands still ask for approval before execution.
                </p>
                <div
                  style={{
                    minWidth: isMobile ? '100%' : 240,
                    color: canStart ? 'var(--text-secondary)' : 'var(--text-muted)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 14,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: isMobile ? 'center' : 'flex-start',
                    gap: 10,
                    opacity: canStart ? 1 : 0.8,
                  }}
                >
                  <button
                    onClick={start}
                    disabled={!canStart}
                    style={{
                      width: 42,
                      height: 42,
                      borderRadius: 999,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      background: canStart ? 'var(--action-button-bg)' : 'var(--bg-surface)',
                      color: canStart ? 'var(--action-button-fg)' : 'var(--text-muted)',
                      flexShrink: 0,
                      border: '1px solid var(--border-bright)',
                      cursor: canStart ? 'pointer' : 'not-allowed',
                      padding: 0,
                    }}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 19V5" />
                      <path d="m6 11 6-6 6 6" />
                    </svg>
                  </button>
                  <span style={{ color: canStart ? 'var(--text-primary)' : 'var(--text-muted)' }}>open workspace</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <p style={{ marginTop: 16, fontSize: 11, color: 'var(--text-muted)', textAlign: 'center', fontFamily: 'var(--font-mono)' }}>
          powered by Groq · LLaMA 3.3 70B · local filesystem access
        </p>

        {sortedSessions.length > 0 && (
          <section ref={menuRootRef} style={{ marginTop: 24, display: 'grid', gap: 18 }}>
            <div style={{ display: 'grid', gap: 18 }}>
              {renderSessionSection('starred', starredSessions)}
              {renderSessionSection(starredSessions.length > 0 ? 'recent' : 'recent sessions', unstarredSessions)}
            </div>
          </section>
        )}
      </div>

      {renameSessionId && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.28)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, zIndex: 30 }}>
          <div style={{ width: '100%', maxWidth: 420, borderRadius: 16, background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: 'var(--shadow-lg)', padding: 18 }}>
            <p style={{ fontSize: 15, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>rename session</p>
            <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6 }}>give this chat a clearer terminal label</p>
            <input
              value={renameValue}
              onChange={event => setRenameValue(event.target.value)}
              placeholder="session name"
              autoFocus
              style={{ width: '100%', marginTop: 14, background: 'var(--bg-raised)', border: '1px solid var(--border)', borderRadius: 10, padding: '11px 12px', color: 'var(--text-primary)', fontSize: 14, outline: 'none', fontFamily: 'var(--font-mono)' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 16 }}>
              <button onClick={() => setRenameSessionId(null)} style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg-surface)', color: 'var(--text-primary)', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
                cancel
              </button>
              <button onClick={renameSession} style={{ padding: '10px 12px', borderRadius: 10, border: 'none', background: 'var(--accent)', color: 'var(--accent-contrast)', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
                save
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteSessionTarget && (
        <div
          onClick={() => setDeleteSessionTarget(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.34)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, zIndex: 31 }}
        >
          <div
            onClick={event => event.stopPropagation()}
            style={{ width: '100%', maxWidth: 460, borderRadius: 18, background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: 'var(--shadow-lg)', padding: '22px 22px 18px' }}
          >
            <p style={{ fontSize: 18, color: 'var(--text-primary)', fontWeight: 600 }}>
              Delete chat
            </p>
            <p style={{ marginTop: 10, fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
              Are you sure you want to delete <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{deleteSessionTarget.title || projectName(deleteSessionTarget.workspace)}</span>?
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 22 }}>
              <button
                onClick={() => setDeleteSessionTarget(null)}
                style={{ padding: '10px 14px', borderRadius: 12, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-primary)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 13 }}
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  const sessionId = deleteSessionTarget.session_id
                  setDeleteSessionTarget(null)
                  await deleteSession(sessionId)
                }}
                style={{ padding: '10px 14px', borderRadius: 12, border: 'none', background: 'var(--red)', color: '#fff7f7', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 13 }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
