
import './App.css'
import { PDFViewer } from '@embedpdf/react-pdf-viewer'
import type { PDFViewerRef } from '@embedpdf/react-pdf-viewer'
import { useRef, useEffect } from 'react'

interface AppProps {
  themePreference?: 'light' | 'dark'
}

export default function App({ themePreference = 'light' }: AppProps) {
  const viewerRef = useRef<PDFViewerRef | null>(null)

  useEffect(() => {
    viewerRef.current?.container?.setTheme({ preference: themePreference })
  }, [themePreference])

  return (
    <div className="h-[760px] w-full overflow-hidden rounded-xl border border-gray-300 shadow-lg dark:border-gray-600">
      <PDFViewer
        ref={viewerRef}
        config={{
          src: 'https://snippet.embedpdf.com/ebook.pdf',
          theme: { preference: themePreference },
        }}
        style={{ width: '100%', height: '100%' }}
      />
    </div>
  )
}
