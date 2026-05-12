import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast' // Importamos toast para dar feedback visual
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

  // Cargar archivos recientes al montar
  useEffect(() => {
    getRecentFiles()
      .then(setRecentFiles)
      .catch((err) => {
        console.error('Error al cargar archivos recientes:', err)
        setRecentFiles([]) // Asegura que el estado no quede roto
      })
  }, [setRecentFiles])

  // Manejo robusto de apertura de archivos recientes
  const handleOpenRecent = async (path: string) => {
    const loadingToast = toast.loading('Abriendo archivo...')
    
    try {
      const result = await openPdf(path)
      
      if (!result) {
        throw new Error('No se pudo leer el archivo')
      }
      
      setCurrentPdf(result)
      toast.dismiss(loadingToast) // Quitamos el loading si fue exitoso
      
      // Al navegar a /ocr (tu visor principal con pestañas), el archivo
      // se agregará automáticamente al DocumentManager gracias a nuestro useEffect allá.
      navigate('/ocr')
      
    } catch (error) {
      toast.error('Error al abrir. ¿El archivo fue movido o borrado?', { 
        id: loadingToast 
      })
    }
  }

  return (
    // Se usa div en lugar de main porque App.tsx ya provee el <main>
    // h-full y w-full respetan el layout flexbox global sin desbordarse
    <div className="grid h-full w-full grid-cols-1 lg:grid-cols-[280px_1fr]">
      <Sidebar files={recentFiles} onSelect={handleOpenRecent} />
      <QuickActions 
        actions={quickActions} 
        onSelect={(action) => navigate(action.to)} 
      />
    </div>
  )
}
