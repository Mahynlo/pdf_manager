import { PDFViewer } from '@embedpdf/react-pdf-viewer'
import type { PDFViewerRef } from '@embedpdf/react-pdf-viewer'
import { useEffect, useRef, useState } from 'react'
import { openPdf, pickFiles } from '../services/api'
import { useAppState } from '../state/AppContext'

interface AppProps {
  themePreference?: 'light' | 'dark'
}

export function OcrPage({ themePreference = 'light' }: AppProps) {
  const viewerRef = useRef<PDFViewerRef | null>(null)
  const { currentPdf, setCurrentPdf } = useAppState()
  const [status, setStatus] = useState('Selecciona un PDF para comenzar.')

  useEffect(() => {
    viewerRef.current?.container?.setTheme({ preference: themePreference })
  }, [themePreference])

  const handleOpen = async () => {
    const files = await pickFiles({ multiple: false, title: 'Seleccionar PDF' })
    if (!files.length) {
      return
    }
    const result = await openPdf(files[0])
    if (!result) {
      return
    }
    setCurrentPdf(result)
    setStatus(`Documento cargado: ${result.name}`)
  }

  return (
    // 1. Cambiamos a h-full (o h-screen si es la raíz de la vista) para tomar todo el alto
    <div className="flex h-full min-h-screen flex-col gap-4 p-6">
      
      {/* Barra de herramientas (mantiene su tamaño natural) */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#e3e8ef] bg-white/70 px-5 py-3 shrink-0">
        <div>
          <h2 className="text-sm font-semibold text-[#0f1824]">OCR de PDF</h2>
          <p className="text-xs text-[#5a6b7f]">{status}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleOpen}
            className="rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64] hover:bg-gray-50 transition-colors"
          >
            Abrir PDF
          </button>
          <button
            type="button"
            className="rounded-full bg-[#365b89] px-4 py-2 text-xs font-semibold text-white hover:bg-[#2a476b] transition-colors"
          >
            Iniciar OCR
          </button>
        </div>
      </div>

      {/* 2. flex-1 para absorber el espacio restante y min-h-0 para evitar desbordamientos */}
      <div style={{ height: '100vh' }}>
        <PDFViewer
          ref={viewerRef}
          config={{
            src: currentPdf?.dataUrl ?? '',
            theme: { preference: themePreference },
          }}
          style={{ width: '100%', height: '100%' }}
        />
      </div>
    </div>
  )
}
