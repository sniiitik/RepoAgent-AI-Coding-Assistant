'use client'
import { useState, useEffect, useRef, Suspense } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'

type AgentEvent =
    | { type: 'thought'; content: string }
    | { type: 'tool_call'; tool: string; args: Record<string, unknown> }
    | { type: 'tool_result'; tool: string; result: Record<string, unknown> }
    | { type: 'file_changed'; path: string; original: string; new_content: string }
    | { type: 'done'; content: string; changed_files: FileChange[]; iterations: number }
    | { type: 'error'; content: string }

type FileChange = { path: string; original: string; new_content: string }

function ToolIcon({ tool }: { tool: string }) {
    const icons: Record<string, string> = { list_files: '≡', read_file: '↓', write_file: '↑', search_code: '⌕', run_command: '$' }
    return <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.7 }}>{icons[tool] ?? '·'}</span>
}

function DiffViewer({ original, newContent, path }: { original: string; newContent: string; path: string }) {
    const [open, setOpen] = useState(false)
    const origLines = (original || '').split('\n')
    const newLines = newContent.split('\n')

    // Simple unified diff — highlight added/removed lines
    const maxLen = Math.max(origLines.length, newLines.length)
    const rows: { type: 'add' | 'remove' | 'same'; text: string; lineNo: number }[] = []

    // Very simple diff: line-by-line comparison
    const seen = new Set<number>()
    for (let i = 0; i < newLines.length; i++) {
        if (origLines[i] === undefined) {
            rows.push({ type: 'add', text: newLines[i], lineNo: i + 1 })
        } else if (origLines[i] !== newLines[i]) {
            rows.push({ type: 'remove', text: origLines[i], lineNo: i + 1 })
            rows.push({ type: 'add', text: newLines[i], lineNo: i + 1 })
            seen.add(i)
        } else {
            rows.push({ type: 'same', text: newLines[i], lineNo: i + 1 })
        }
    }
    for (let i = newLines.length; i < origLines.length; i++) {
        rows.push({ type: 'remove', text: origLines[i], lineNo: i + 1 })
    }

    const added = rows.filter(r => r.type === 'add').length
    const removed = rows.filter(r => r.type === 'remove').length

    return (
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', marginTop: 4 }}>
            <div onClick={() => setOpen(o => !o)} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '8px 12px', background: 'var(--bg-raised)', cursor: 'pointer',
            }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)' }}>{path}</span>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {added > 0 && <span style={{ fontSize: 11, color: 'var(--green)', fontFamily: 'var(--font-mono)' }}>+{added}</span>}
                    {removed > 0 && <span style={{ fontSize: 11, color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>−{removed}</span>}
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                        style={{ transform: open ? 'rotate(90deg)' : 'none', transition: '0.15s', opacity: 0.5 }}>
                        <polyline points="9 18 15 12 9 6" />
                    </svg>
                </div>
            </div>
            {open && (
                <div style={{ maxHeight: 360, overflow: 'auto' }}>
                    <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.5, padding: 0, margin: 0 }}>
                        {rows.map((row, i) => (
                            <div key={i} className={row.type === 'add' ? 'diff-add' : row.type === 'remove' ? 'diff-remove' : 'diff-neutral'}
                                style={{
                                    padding: '1px 12px', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                                    color: row.type === 'add' ? 'var(--green)' : row.type === 'remove' ? 'var(--red)' : 'var(--text-secondary)'
                                }}>
                                {row.type === 'add' ? '+ ' : row.type === 'remove' ? '− ' : '  '}{row.text}
                            </div>
                        ))}
                    </pre>
                </div>
            )}
        </div>
    )
}

function EventRow({ event, index }: { event: AgentEvent; index: number }) {
    const [showResult, setShowResult] = useState(false)
    const delay = `${Math.min(index * 0.03, 0.3)}s`

    if (event.type === 'thought') return (
        <div className="fade-in" style={{ animationDelay: delay, display: 'flex', gap: 10, alignItems: 'flex-start', padding: '6px 0' }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', marginTop: 5, flexShrink: 0 }} />
            <p style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{event.content}</p>
        </div>
    )

    if (event.type === 'tool_call') return (
        <div className="fade-in" style={{ animationDelay: delay, display: 'flex', gap: 10, alignItems: 'center', padding: '5px 0' }}>
            <div style={{ width: 6, height: 6, borderRadius: 2, background: 'var(--purple)', flexShrink: 0 }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--purple)' }}>{event.tool}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {JSON.stringify(event.args)}
            </span>
        </div>
    )

    if (event.type === 'tool_result') return (
        <div className="fade-in" style={{ animationDelay: delay, paddingLeft: 16 }}>
            <button onClick={() => setShowResult(s => !s)} style={{
                fontSize: 11, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 0'
            }}>
                {showResult ? '▾' : '▸'} {event.tool} result
            </button>
            {showResult && (
                <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', background: 'var(--bg-raised)', padding: '8px 12px', borderRadius: 6, overflow: 'auto', maxHeight: 200, marginTop: 4 }}>
                    {JSON.stringify(event.result, null, 2)}
                </pre>
            )}
        </div>
    )

    if (event.type === 'file_changed') return (
        <div className="fade-in" style={{ animationDelay: delay, paddingLeft: 16 }}>
            <DiffViewer path={event.path} original={event.original} newContent={event.new_content} />
        </div>
    )

    if (event.type === 'error') return (
        <div className="fade-in" style={{ animationDelay: delay, padding: '8px 12px', borderRadius: 6, background: 'var(--red-dim)', border: '1px solid rgba(248,81,73,0.2)', fontSize: 13, color: 'var(--red)' }}>
            Error: {event.content}
        </div>
    )

    return null
}

function SessionContent() {
    const params = useSearchParams()
    const router = useRouter()
    const goal = params.get('goal') || ''
    const mode = params.get('mode') || 'refactor'
    const workspace = params.get('workspace') || ''

    const [events, setEvents] = useState<AgentEvent[]>([])
    const [status, setStatus] = useState<'running' | 'done' | 'error'>('running')
    const [summary, setSummary] = useState('')
    const [changedFiles, setChangedFiles] = useState<FileChange[]>([])
    const [iterations, setIterations] = useState(0)
    const bottomRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [events])

    useEffect(() => {
        if (!goal || !workspace) return
        const controller = new AbortController()

        const backendUrl = (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000').replace(/\/+$/, '')
        const apiUrl = `${backendUrl}/api/run`

        fetch(apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ goal, mode, workspace }),
            signal: controller.signal,
        }).then(async res => {
            if (!res.ok) { setStatus('error'); return }
            if (!res.body) { setStatus('error'); return }

            const reader = res.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''

            while (true) {
                const { done, value } = await reader.read()
                if (done) {
                    if (buffer.length) {
                        const line = buffer.trim()
                        if (line.startsWith('data: ')) {
                            const raw = line.slice(6).trim()
                            if (raw === '[DONE]') setStatus('done')
                            else {
                                try {
                                    const event: AgentEvent = JSON.parse(raw)
                                    setEvents(prev => [...prev, event])
                                } catch { }
                            }
                        }
                    }
                    break
                }

                buffer += decoder.decode(value, { stream: true })

                let newlineIndex = buffer.indexOf('\n')
                while (newlineIndex !== -1) {
                    const line = buffer.slice(0, newlineIndex).trim()
                    buffer = buffer.slice(newlineIndex + 1)
                    if (!line.startsWith('data: ')) {
                        newlineIndex = buffer.indexOf('\n')
                        continue
                    }
                    const raw = line.slice(6).trim()
                    if (raw === '[DONE]') {
                        setStatus('done')
                        return
                    }
                    try {
                        const event: AgentEvent = JSON.parse(raw)
                        setEvents(prev => [...prev, event])
                        if (event.type === 'done') {
                            setStatus('done')
                            setSummary(event.content)
                            setChangedFiles(event.changed_files)
                            setIterations(event.iterations)
                        }
                        if (event.type === 'error') setStatus('error')
                    } catch {
                        // malformed event chunk
                    }
                    newlineIndex = buffer.indexOf('\n')
                }
            }
        }).catch(e => { if (e.name !== 'AbortError') setStatus('error') })

        return () => controller.abort()
    }, [goal, mode, workspace])

    const modeColor: Record<string, string> = { refactor: 'var(--accent)', test: 'var(--green)', document: 'var(--orange)' }

    return (
        <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>

            {/* Topbar */}
            <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', gap: 12 }}>
                <button onClick={() => router.push('/')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: 13, display: 'flex', alignItems: 'center', gap: 4 }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6" /></svg>
                    New run
                </button>
                <div style={{ width: 1, height: 16, background: 'var(--border)' }} />
                <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: modeColor[mode] || 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{mode}</span>
                <p style={{ fontSize: 13, color: 'var(--text-secondary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{goal}</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {status === 'running' && <><div className="spinner" /><span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Running…</span></>}
                    {status === 'done' && <span style={{ fontSize: 12, color: 'var(--green)' }}>Done · {iterations} steps · {changedFiles.length} file{changedFiles.length !== 1 ? 's' : ''} changed</span>}
                    {status === 'error' && <span style={{ fontSize: 12, color: 'var(--red)' }}>Error</span>}
                </div>
            </div>

            {/* Content */}
            <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 300px' }}>

                {/* Event stream */}
                <div style={{ padding: '20px 24px', overflow: 'auto', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {events.map((e, i) => <EventRow key={i} event={e} index={i} />)}
                    {status === 'running' && (
                        <div style={{ display: 'flex', gap: 6, padding: '8px 0', alignItems: 'center' }}>
                            <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', animation: 'pulse 1s infinite' }} />
                            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Agent thinking…</span>
                        </div>
                    )}
                    {status === 'done' && summary && (
                        <div style={{ marginTop: 12, padding: '12px 16px', borderRadius: 8, background: 'var(--green-dim)', border: '1px solid rgba(63,185,80,0.2)' }}>
                            <p style={{ fontSize: 13, color: 'var(--green)', fontWeight: 500, marginBottom: 4 }}>Completed</p>
                            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{summary}</p>
                        </div>
                    )}
                    <div ref={bottomRef} />
                </div>

                {/* Sidebar — changed files */}
                <div style={{ padding: '16px', overflow: 'auto' }}>
                    <p style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
                        Changed files ({changedFiles.length})
                    </p>
                    {changedFiles.length === 0 && status === 'running' && (
                        <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>Waiting for file changes…</p>
                    )}
                    {changedFiles.map((f, i) => (
                        <div key={i} style={{ padding: '8px 10px', borderRadius: 6, background: 'var(--bg-raised)', border: '1px solid var(--border)', marginBottom: 6 }}>
                            <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', wordBreak: 'break-all' }}>{f.path}</p>
                            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                                {(f.original || '').split('\n').length} → {f.new_content.split('\n').length} lines
                            </p>
                        </div>
                    ))}

                    {/* Workspace info */}
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