import { createContext, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { RecentFile } from '../services/api'

type AppState = {
  recentFiles: RecentFile[]
  setRecentFiles: (files: RecentFile[]) => void
  currentPdf: { name: string; path: string; dataUrl: string } | null
  setCurrentPdf: (pdf: { name: string; path: string; dataUrl: string } | null) => void
}

const AppContext = createContext<AppState | undefined>(undefined)

export function AppProvider({ children }: { children: ReactNode }) {
  const [recentFiles, setRecentFiles] = useState<RecentFile[]>([])
  const [currentPdf, setCurrentPdf] = useState<AppState['currentPdf']>(null)

  const value = useMemo(
    () => ({
      recentFiles,
      setRecentFiles,
      currentPdf,
      setCurrentPdf,
    }),
    [recentFiles, currentPdf],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useAppState() {
  const ctx = useContext(AppContext)
  if (!ctx) {
    throw new Error('useAppState must be used within AppProvider')
  }
  return ctx
}
