import { useNavigate } from 'react-router-dom'
import { QuickActions } from '../components/QuickActions'
import { Sidebar } from '../components/Sidebar'
import { MagnifyIcon, MergeIcon, OcrIcon } from '../components/icons'

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

const recentFiles = [
  { name: 'OFICIO_CARLOS_CA...', path: 'C:\\Users\\CFE\\Downloads' },
  { name: 'combinado_de_100...', path: 'C:\\Users\\CFE\\Document...' },
  { name: 'ejemplo_PDFjs.pdf', path: 'C:\\Users\\CFE\\Document...' },
  { name: 'AURELIANO_HERN...', path: 'C:\\Users\\CFE\\Document...' },
  { name: 'documento_1.pdf', path: 'C:\\Users\\CFE\\Document...' },
  { name: 'redes_de_computad...', path: 'E:\\Programas_exe' },
  { name: '26 Vigesima sexta s...', path: 'C:\\Users\\CFE\\Document...' },
  { name: '130006633 CARLOS ...', path: 'C:\\Users\\CFE\\Document...' },
  { name: 'MAR 113 2022 SAUL...', path: 'C:\\Users\\CFE\\Document...' },
  { name: 'OFICIO_CARLOS_CA...', path: 'C:\\Users\\CFE\\Desktop' },
]

export function HomePage() {
  const navigate = useNavigate()

  return (
    <main className="grid min-h-[calc(100vh-120px)] grid-cols-1 lg:grid-cols-[280px_1fr]">
      <Sidebar files={recentFiles} />
      <QuickActions actions={quickActions} onSelect={(action) => navigate(action.to)} />
    </main>
  )
}
