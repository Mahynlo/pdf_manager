
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
    <div className="flex min-h-[calc(100vh-120px)] flex-col gap-4 px-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#e3e8ef] bg-white/70 px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold text-[#0f1824]">OCR de PDF</h2>
          <p className="text-xs text-[#5a6b7f]">{status}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleOpen}
            className="rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]"
          >
            Abrir PDF
          </button>
          <button
            type="button"
            className="rounded-full bg-[#365b89] px-4 py-2 text-xs font-semibold text-white"
          >
            Iniciar OCR
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden rounded-2xl border border-[#e3e8ef] bg-white shadow-sm">
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
