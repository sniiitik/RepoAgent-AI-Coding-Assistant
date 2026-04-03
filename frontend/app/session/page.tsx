'use client'

import { Suspense, useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

type AgentEvent =
  | { type: 'thought'; content: string }
  | { type: 'tool_call'; tool: string; args: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; result: Record<string, unknown> }
  | { type: 'file_changed'; path: string; original: string; new_content: string }
  | { type: 'done'; content: string; changed_files: FileChange[]; iterations: number }
  | { type: 'error'; content: string }

type FileChange = { path: string; original: string; new_content: string }

type ChatTurn = {
  id: number
  goal: string
  status: 'running' | 'done' | 'error'
  events: AgentEvent[]
  summary: string
  changedFiles: FileChange[]
  iterations: number
}

type SessionPayload = {
  session_id: string
  workspace: string
  mode: string
  busy: boolean
}

function DiffViewer({ original, newContent, path }: { original: string; newContent: string; path: string }) {
  const [open, setOpen] = useState(false)
  const origLines = (original || '').split('\n')
  const newLines = newContent.split('\n')
  const rows: { type: 'add' | 'remove' | 'same'; text: string }[] = []

  for (let i = 0; i < newLines.length; i++) {
    if (origLines[i] === undefined) rows.push({ type: 'add', text: newLines[i] })
    else if (origLines[i] !== newLines[i]) {
      rows.push({ type: 'remove', text: origLines[i] })
      rows.push({ type: 'add', text: newLines[i] })
    } else rows.push({ type: 'same', text: newLines[i] })
  }
  for (let i = newLines.length; i < origLines.length; i++) rows.push({ type: 'remove', text: origLines[i] })

  const added = rows.filter(row => row.type === 'add').length
  const removed = rows.filter(row => row.type === 'remove').length

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', marginTop: 6 }}>
      <div
        onClick={() => setOpen(current => !current)}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', background: 'var(--bg-raised)', cursor: 'pointer' }}
      >
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)' }}>{path}</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {added > 0 && <span style={{ fontSize: 11, color: 'var(--green)', fontFamily: 'var(--font-mono)' }}>+{added}</span>}
          {removed > 0 && <span style={{ fontSize: 11, color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>-{removed}</span>}
        </div>
      </div>
      {open && (
        <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.5, margin: 0, maxHeight: 320, overflow: 'auto' }}>
          {rows.map((row, index) => (
            <div
              key={index}
              style={{
                padding: '1px 12px',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                color: row.type === 'add' ? 'var(--green)' : row.type === 'remove' ? 'var(--red)' : 'var(--text-secondary)',
              }}
            >
              {row.type === 'add' ? '+ ' : row.type === 'remove' ? '- ' : '  '}
              {row.text}
            </div>
          ))}
        </pre>
      )}
    </div>
  )
}

function TurnEvent({ event }: { event: AgentEvent }) {
  const [showResult, setShowResult] = useState(false)

  if (event.type === 'thought') {
    return (
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '5px 0' }}>
        <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', marginTop: 6, flexShrink: 0 }} />
        <p style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{event.content}</p>
      </div>
    )
  }

  if (event.type === 'tool_call') {
    return (
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '4px 0 4px 16px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--orange)' }}>{event.tool}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {JSON.stringify(event.args)}
        </span>
      </div>
    )
  }

  if (event.type === 'tool_result') {
    return (
      <div style={{ paddingLeft: 16 }}>
        <button
          onClick={() => setShowResult(current => !current)}
          style={{ fontSize: 11, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 0' }}
        >
          {showResult ? 'Hide' : 'Show'} {event.tool} result
        </button>
        {showResult && (
          <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', background: 'var(--bg-raised)', padding: '8px 12px', borderRadius: 6, overflow: 'auto', maxHeight: 220, marginTop: 4 }}>
            {JSON.stringify(event.result, null, 2)}
          </pre>
        )}
      </div>
    )
  }

  if (event.type === 'file_changed') {
    return (
      <div style={{ paddingLeft: 16 }}>
        <DiffViewer path={event.path} original={event.original} newContent={event.new_content} />
      </div>
    )
  }

  if (event.type === 'error') {
    return (
      <div style={{ padding: '8px 12px', borderRadius: 6, background: 'var(--red-dim)', border: '1px solid rgba(248,81,73,0.2)', fontSize: 13, color: 'var(--red)' }}>
        Error: {event.content}
      </div>
    )
  }

  return null
}

function ChatTurnCard({ turn }: { turn: ChatTurn }) {
  const statusColor = turn.status === 'done' ? 'var(--green)' : turn.status === 'error' ? 'var(--red)' : 'var(--accent)'
  const showGeneratingBubble = turn.status === 'running' && turn.events.length === 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ alignSelf: 'flex-end', maxWidth: '80%', padding: '12px 14px', borderRadius: 12, background: 'var(--accent-dim)', border: '1px solid rgba(88,166,255,0.25)' }}>
        <p style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>You</p>
        <p style={{ fontSize: 14, color: 'var(--text-primary)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{turn.goal}</p>
      </div>

      <div style={{ maxWidth: '90%', padding: '14px 16px', borderRadius: 12, background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>RepoAgent</p>
          <span style={{ fontSize: 12, color: statusColor }}>
            {turn.status === 'running' ? 'Running...' : turn.status === 'done' ? `Done in ${turn.iterations} steps` : 'Error'}
          </span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {showGeneratingBubble && (
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0' }}>
              <div className="spinner" />
              <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>RepoAgent is thinking...</p>
            </div>
          )}
          {turn.events.map((event, index) => <TurnEvent key={`${turn.id}-${index}`} event={event} />)}
          {turn.status === 'done' && turn.summary && (
            <div style={{ marginTop: 6, padding: '12px 14px', borderRadius: 8, background: 'var(--green-dim)', border: '1px solid rgba(63,185,80,0.2)' }}>
              <p style={{ fontSize: 13, color: 'var(--green)', lineHeight: 1.6 }}>{turn.summary}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SessionContent() {
  const params = useSearchParams()
  const router = useRouter()
  const backendUrl = useMemo(() => (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000').replace(/\/+$/, ''), [])
  const workspaceParam = params.get('workspace') || ''
  const sessionParam = params.get('session') || ''
  const initialGoalParam = params.get('goal') || ''
  const defaultMode = 'refactor'

  const [sessionId, setSessionId] = useState(sessionParam)
  const [workspace, setWorkspace] = useState(workspaceParam)
  const [input, setInput] = useState(initialGoalParam)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [status, setStatus] = useState<'booting' | 'idle' | 'running' | 'error'>('booting')
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const initialGoalSentRef = useRef(false)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, status])

  useEffect(() => {
    let cancelled = false

    async function loadSession() {
      if (sessionParam) {
        try {
          const res = await fetch(`${backendUrl}/api/sessions/${sessionParam}`)
          if (!res.ok) throw new Error('Unable to load this session')
          const data: SessionPayload = await res.json()
          if (cancelled) return
          setSessionId(data.session_id)
          setWorkspace(data.workspace)
          setStatus(data.busy ? 'running' : 'idle')
          setError('')
        } catch (e) {
          if (cancelled) return
          setStatus('error')
          setError(e instanceof Error ? e.message : 'Unable to load this session')
        }
        return
      }

      if (!workspaceParam) {
        setStatus('error')
        setError('Workspace path is missing')
        return
      }

      try {
        const res = await fetch(`${backendUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace: workspaceParam, mode: defaultMode }),
        })
        if (!res.ok) {
          const message = await res.text()
          throw new Error(message || 'Unable to create a session')
        }
        const data: SessionPayload = await res.json()
        if (cancelled) return
        setSessionId(data.session_id)
        setWorkspace(data.workspace)
        setStatus('idle')
        setError('')
        router.replace(`/session?session=${data.session_id}`)
      } catch (e) {
        if (cancelled) return
        setStatus('error')
        setError(e instanceof Error ? e.message : 'Unable to create a session')
      }
    }

    loadSession()
    return () => {
      cancelled = true
    }
  }, [backendUrl, defaultMode, router, sessionParam, workspaceParam])

  function updateTurn(turnId: number, mutate: (turn: ChatTurn) => ChatTurn) {
    setTurns(previous => previous.map(turn => (turn.id === turnId ? mutate(turn) : turn)))
  }

  async function sendMessage(goal: string) {
    if (!sessionId || !goal.trim() || status === 'running') return

    const turnId = Date.now()
    const nextTurn: ChatTurn = {
      id: turnId,
      goal: goal.trim(),
      status: 'running',
      events: [],
      summary: '',
      changedFiles: [],
      iterations: 0,
    }

    setTurns(previous => [...previous, nextTurn])
    setInput('')
    setStatus('running')
    setError('')

    try {
      const res = await fetch(`${backendUrl}/api/sessions/${sessionId}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: goal.trim(), mode: defaultMode }),
      })
      if (!res.ok) {
        const message = await res.text()
        throw new Error(message || 'Request failed')
      }
      if (!res.body) throw new Error('Streaming response missing')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
          const chunk = buffer.slice(0, boundary).trim()
          buffer = buffer.slice(boundary + 2)

          if (!chunk.startsWith('data: ')) {
            boundary = buffer.indexOf('\n\n')
            continue
          }

          const raw = chunk.slice(6).trim()
          if (raw === '[DONE]') {
            setStatus('idle')
            boundary = buffer.indexOf('\n\n')
            continue
          }

          const event: AgentEvent = JSON.parse(raw)
          updateTurn(turnId, turn => {
            const updatedTurn: ChatTurn = { ...turn, events: [...turn.events, event] }
            if (event.type === 'done') {
              updatedTurn.status = 'done'
              updatedTurn.summary = event.content
              updatedTurn.changedFiles = event.changed_files
              updatedTurn.iterations = event.iterations
            }
            if (event.type === 'error') updatedTurn.status = 'error'
            return updatedTurn
          })

          if (event.type === 'done') setStatus('idle')
          if (event.type === 'error') {
            setStatus('error')
            setError(event.content)
          }

          boundary = buffer.indexOf('\n\n')
        }
      }

      setStatus(current => (current === 'running' ? 'idle' : current))
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Request failed'
      updateTurn(turnId, turn => ({
        ...turn,
        status: 'error',
        events: [...turn.events, { type: 'error', content: message }],
      }))
      setStatus('error')
      setError(message)
    }
  }

  const sendInitialGoal = useEffectEvent(() => {
    sendMessage(initialGoalParam)
  })

  useEffect(() => {
    if (!sessionId || !initialGoalParam || initialGoalSentRef.current) return
    initialGoalSentRef.current = true
    sendInitialGoal()
  }, [initialGoalParam, sessionId])

  const latestChangedFiles = [...turns].reverse().find(turn => turn.changedFiles.length > 0)?.changedFiles ?? []

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <button onClick={() => router.push('/')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: 13 }}>
          New workspace
        </button>
        <div style={{ width: 1, height: 16, background: 'var(--border)' }} />
        <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
          {sessionId ? `session ${sessionId.slice(0, 8)}` : 'creating session'}
        </span>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{workspace || 'No workspace loaded'}</p>
        <span style={{ fontSize: 12, color: status === 'running' ? 'var(--accent)' : status === 'error' ? 'var(--red)' : 'var(--green)' }}>
          {status === 'booting' ? 'Connecting...' : status === 'running' ? 'Running...' : status === 'error' ? 'Attention needed' : 'Ready'}
        </span>
      </div>

      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', minHeight: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '20px 24px 28px', display: 'flex', flexDirection: 'column', gap: 18 }}>
            {turns.length === 0 && status !== 'error' && (
              <div style={{ padding: '18px 20px', borderRadius: 12, background: 'var(--bg-surface)', border: '1px solid var(--border)', maxWidth: 620 }}>
                <p style={{ fontSize: 14, color: 'var(--text-primary)', lineHeight: 1.7 }}>
                  Workspace is loaded. Ask for anything next: create a README, explain the architecture, change a file, add tests, or refine a previous result.
                </p>
              </div>
            )}

            {turns.map(turn => <ChatTurnCard key={turn.id} turn={turn} />)}

            {error && status === 'error' && (
              <div style={{ maxWidth: 620, padding: '12px 14px', borderRadius: 10, background: 'var(--red-dim)', border: '1px solid rgba(248,81,73,0.2)', color: 'var(--red)', fontSize: 13 }}>
                {error}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div style={{ position: 'sticky', bottom: 0, padding: '16px 24px 22px', borderTop: '1px solid var(--border)', background: 'linear-gradient(180deg, rgba(22,27,34,0.92) 0%, rgba(13,17,23,0.98) 100%)', backdropFilter: 'blur(14px)' }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', padding: '10px 12px', borderRadius: 24, border: '1px solid var(--border)', background: 'rgba(33,38,45,0.9)', boxShadow: '0 16px 40px rgba(0,0,0,0.28)' }}>
              <textarea
                value={input}
                onChange={event => setInput(event.target.value)}
                placeholder="Ask a follow-up about this workspace..."
                rows={2}
                disabled={status === 'booting'}
                style={{ flex: 1, minHeight: 56, maxHeight: 120, background: 'transparent', border: 'none', padding: '8px 10px 6px', color: 'var(--text-primary)', fontSize: 14, resize: 'none', outline: 'none', lineHeight: 1.45 }}
              />

              <button
                onClick={() => sendMessage(input)}
                disabled={status === 'running' || status === 'booting' || !input.trim() || !sessionId}
                style={{
                  width: 42,
                  height: 42,
                  flexShrink: 0,
                  borderRadius: 14,
                  border: '1px solid rgba(88,166,255,0.18)',
                  background: status === 'running' ? 'rgba(88,166,255,0.08)' : 'linear-gradient(135deg, #79c0ff 0%, #58a6ff 55%, #3b82f6 100%)',
                  color: status === 'running' ? 'var(--text-muted)' : '#07111f',
                  cursor: status === 'running' ? 'default' : 'pointer',
                  boxShadow: status === 'running' ? 'none' : '0 10px 24px rgba(88,166,255,0.28)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                }}
                aria-label={status === 'running' ? 'Working' : 'Send message'}
                title={status === 'running' ? 'Working...' : 'Send'}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  {status === 'running' ? (
                    <>
                      <path d="M12 6v2" />
                      <path d="M12 16v2" />
                      <path d="M6 12h2" />
                      <path d="M16 12h2" />
                    </>
                  ) : (
                    <>
                      <path d="M12 19V5" />
                      <path d="m6 11 6-6 6 6" />
                    </>
                  )}
                </svg>
              </button>
            </div>
          </div>
        </div>

        <div style={{ padding: '16px', overflow: 'auto', borderLeft: '1px solid var(--border)' }}>
          <p style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
            Latest changed files ({latestChangedFiles.length})
          </p>

          {latestChangedFiles.length === 0 && <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>No file edits in the latest completed run yet.</p>}

          {latestChangedFiles.map((file, index) => (
            <div key={`${file.path}-${index}`} style={{ padding: '8px 10px', borderRadius: 6, background: 'var(--bg-raised)', border: '1px solid var(--border)', marginBottom: 6 }}>
              <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', wordBreak: 'break-all' }}>{file.path}</p>
              <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                {(file.original || '').split('\n').length} to {file.new_content.split('\n').length} lines
              </p>
            </div>
          ))}

          <div style={{ marginTop: 20, padding: '10px 12px', borderRadius: 6, background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Workspace</p>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-secondary)', wordBreak: 'break-all' }}>{workspace}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function SessionPage() {
  return (
    <Suspense>
      <SessionContent />
    </Suspense>
  )
}
