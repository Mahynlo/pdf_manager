import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { QuickActions } from '../components/QuickActions'
import { Sidebar } from '../components/Sidebar'
import { MagnifyIcon, MergeIcon, OcrIcon } from '../components/icons'
import { getRecentFiles, openPdf } from '../services/api'
import { useAppState } from '../state/AppContext'

const quickActions = [
  {
    title: 'Extraer texto de PDF',
    description: 'Busca y extrae paginas por palabras clave',
    tone: 'info' as const,
    to: '/extract',
    icon: <MagnifyIcon />,
  },
  {
    title: 'Combinar PDFs',
    description: 'Une varios PDFs eligiendo las paginas',
    tone: 'neutral' as const,
    to: '/merge',
    icon: <MergeIcon />,
  },
  {
    title: 'OCR de PDF',
    description: 'Abre un PDF y ejecuta reconocimiento de texto',
    tone: 'accent' as const,
    to: '/ocr',
    icon: <OcrIcon />,
  },
]

export function HomePage() {
  const navigate = useNavigate()
  const { recentFiles, setRecentFiles, setCurrentPdf } = useAppState()

  useEffect(() => {
    getRecentFiles().then(setRecentFiles).catch(() => setRecentFiles([]))
  }, [setRecentFiles])

  const handleOpenRecent = async (path: string) => {
    const result = await openPdf(path)
    if (!result) {
      return
    }
    setCurrentPdf(result)
    navigate('/ocr')
  }

  return (
    <main className="grid min-h-[calc(100vh-120px)] grid-cols-1 lg:grid-cols-[280px_1fr]">
      <Sidebar files={recentFiles} onSelect={handleOpenRecent} />
      <QuickActions actions={quickActions} onSelect={(action) => navigate(action.to)} />
    </main>
  )
}
