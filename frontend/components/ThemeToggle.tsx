'use client'

import { useSyncExternalStore } from 'react'

import { useTheme } from './ThemeProvider'

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4.5" />
      <path d="M12 2.5v2.5" />
      <path d="M12 19v2.5" />
      <path d="M4.9 4.9 6.7 6.7" />
      <path d="M17.3 17.3 19.1 19.1" />
      <path d="M2.5 12H5" />
      <path d="M19 12h2.5" />
      <path d="m4.9 19.1 1.8-1.8" />
      <path d="m17.3 6.7 1.8-1.8" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
    </svg>
  )
}

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  )

  if (!mounted) {
    return (
      <div style={{ position: 'fixed', right: 20, bottom: 20, zIndex: 50 }}>
        <div style={{ display: 'flex', gap: 4, padding: 4, borderRadius: 999, background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: 'var(--shadow-md)' }}>
          <div style={{ width: 34, height: 34, borderRadius: 999, background: 'transparent' }} />
          <div style={{ width: 34, height: 34, borderRadius: 999, background: 'transparent' }} />
        </div>
      </div>
    )
  }

  return (
    <div style={{ position: 'fixed', right: 20, bottom: 20, zIndex: 50 }}>
      <div style={{ display: 'flex', gap: 4, padding: 4, borderRadius: 999, background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: 'var(--shadow-md)' }}>
        <button
          onClick={() => setTheme('light')}
          aria-label="Switch to light mode"
          title="Light mode"
          style={{
            width: 34,
            height: 34,
            borderRadius: 999,
            border: 'none',
            background: theme === 'light' ? 'var(--accent)' : 'transparent',
            color: theme === 'light' ? 'var(--accent-contrast)' : 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
          }}
        >
          <SunIcon />
        </button>
        <button
          onClick={() => setTheme('dark')}
          aria-label="Switch to dark mode"
          title="Dark mode"
          style={{
            width: 34,
            height: 34,
            borderRadius: 999,
            border: 'none',
            background: theme === 'dark' ? 'var(--accent)' : 'transparent',
            color: theme === 'dark' ? 'var(--accent-contrast)' : 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
          }}
        >
          <MoonIcon />
        </button>
      </div>
    </div>
  )
}
