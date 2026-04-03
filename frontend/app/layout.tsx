import type { Metadata } from 'next'
import './globals.css'
import ThemeToggle from '../components/ThemeToggle'
import { ThemeProvider } from '../components/ThemeProvider'

export const metadata: Metadata = {
  title: 'CodeMind — AI Coding Agent',
  description: 'Autonomous AI agent that refactors, tests, and documents your code',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <ThemeToggle />
          {children}
        </ThemeProvider>
      </body>
    </html>
  )
}
