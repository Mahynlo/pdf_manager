import { PDFViewer } from '@embedpdf/react-pdf-viewer'
import type { PDFViewerRef } from '@embedpdf/react-pdf-viewer'
import { useEffect, useRef, useState } from 'react'
import { useDocumentManagerCapability, useActiveDocument } from '@embedpdf/plugin-document-manager/react'
import toast, { Toaster } from 'react-hot-toast'
import { ocrPdf, openPdf, pickFiles } from '../services/api'
import type { OpenPdfResult } from '../services/api'
import { useAppState } from '../state/AppContext'

interface AppProps {
  themePreference?: 'light' | 'dark'
}

interface OcrPageData {
  pageNumber: number;
  text: string;
  mode: string;
  usedOcr: boolean;
}

interface DocumentManagerCapability {
  openDocumentUrl(opts: { url: string; name: string; documentId?: string; autoActivate?: boolean }): void;
  openFileDialog?(): void;
  getDocumentCount?(): number;
  onActiveDocumentChanged?: { subscribe(cb: (data: { currentDocumentId: string }) => void): void };
  onDocumentOpened?: { subscribe(cb: (data: { documentId: string; name: string }) => void): void };
  onDocumentClosed?: { subscribe(cb: (data: { documentId: string }) => void): void };
}

interface CommandsCapability {
  registerCommand(command: {
    id: string;
    label: string;
    action: (context: { documentId: string }) => void;
    categories?: string[];
  }): void;
}

interface UICapability {
  getSchema(): {
    toolbars: Record<string, {
      id: string;
      items: Array<{
        type: string;
        id: string;
        items?: Array<any>;
      }>;
    }>;
  };
  mergeSchema(partial: Record<string, unknown>): void;
}

interface PluginRegistry {
  getPlugin(name: 'document-manager'): DocumentManagerCapability;
  getPlugin(name: 'commands'): CommandsCapability;
  getPlugin(name: 'ui'): UICapability;
  getPlugin(name: string): any;
}

export function OcrPage({ themePreference = 'light' }: AppProps) {
  const viewerRef = useRef<PDFViewerRef | null>(null)
  const registryRef = useRef<PluginRegistry | null>(null)
  const docIdCounterRef = useRef<number>(0)
  const openedDocPathsRef = useRef<Set<string>>(new Set())
  const docIdToPathRef = useRef<Map<string, string>>(new Map())
  const docIdToDocRef = useRef<Map<string, OpenPdfResult>>(new Map())

  const { currentPdf, setCurrentPdf } = useAppState()
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null)

  const [ocrResultsByDoc, setOcrResultsByDoc] = useState<Record<string, OcrPageData[]>>({})
  const [activeOcrIdxByDoc, setActiveOcrIdxByDoc] = useState<Record<string, number>>({})

  // NUEVO: Estado para controlar la visibilidad del panel lateral
  const [isSidebarOpen, setIsSidebarOpen] = useState(true)

  // document-manager hooks (provides + active state)
  const { provides: docProvides } = useDocumentManagerCapability()
  const { activeDocumentId: pluginActiveDocumentId } = useActiveDocument()

  const getDocMgr = () => {
    return (docProvides as any) ?? registryRef.current?.getPlugin('document-manager')
  }

  useEffect(() => {
    if (!currentPdf) return
    const docMgr = getDocMgr()
    if (!docMgr) return
    if (openedDocPathsRef.current.has(currentPdf.path)) return

    const docId = `doc-${++docIdCounterRef.current}`

    openedDocPathsRef.current.add(currentPdf.path)
    docIdToPathRef.current.set(docId, currentPdf.path)
    docIdToDocRef.current.set(docId, currentPdf)

    void docMgr.openDocumentUrl({
      url: currentPdf.dataUrl,
      name: currentPdf.name,
      documentId: docId,
      autoActivate: true,
    })

    setActiveDocumentId(docId)
  }, [currentPdf, docProvides])

  useEffect(() => {
    if (!pluginActiveDocumentId) return
    const activeDoc = docIdToDocRef.current.get(pluginActiveDocumentId)
    if (activeDoc && currentPdf?.path !== activeDoc.path) {
      setCurrentPdf(activeDoc)
    }
    setActiveDocumentId(pluginActiveDocumentId)
  }, [pluginActiveDocumentId, currentPdf, setCurrentPdf])

  useEffect(() => {
    viewerRef.current?.container?.setTheme({ preference: themePreference })
  }, [themePreference])

  const ocrPages = activeDocumentId ? (ocrResultsByDoc[activeDocumentId] || []) : []
  const activeOcrIdx = activeDocumentId ? (activeOcrIdxByDoc[activeDocumentId] || 0) : 0
  const hasOpenDocuments = docIdToDocRef.current.size > 0

  const setActiveOcrIdx = (idx: number) => {
    if (!activeDocumentId) return
    setActiveOcrIdxByDoc(prev => ({ ...prev, [activeDocumentId]: idx }))
  }

  const handleOpen = async () => {
    try {
      const files = await pickFiles({ multiple: true, title: 'Seleccionar PDF(s)' })
      if (!files?.length) return

      const docMgr = getDocMgr()
      if (!docMgr) {
        toast.error('DocumentManager no disponible — espere a que cargue el visor')
        return
      }

      const loaded = await Promise.all(files.map((path) => openPdf(path)))
      const valid = loaded.filter((doc): doc is OpenPdfResult => Boolean(doc?.path && doc?.dataUrl))
      if (!valid.length) throw new Error('No se pudo procesar ningún archivo')

      const newDocs = valid.filter(doc => !openedDocPathsRef.current.has(doc.path))

      if (newDocs.length === 0) {
        toast.success('Todos los archivos ya están abiertos')
        return
      }

      for (let i = 0; i < newDocs.length; i++) {
        const doc = newDocs[i]
        const docId = `doc-${++docIdCounterRef.current}`
        const isLast = i === newDocs.length - 1

        openedDocPathsRef.current.add(doc.path)
        docIdToPathRef.current.set(docId, doc.path)
        docIdToDocRef.current.set(docId, doc)

        void docMgr.openDocumentUrl({
          url: doc.dataUrl,
          name: doc.name,
          documentId: docId,
          autoActivate: isLast,
        })

        if (isLast) setActiveDocumentId(docId)
      }

      toast.success(`${newDocs.length} PDF${newDocs.length > 1 ? 's' : ''} cargado${newDocs.length > 1 ? 's' : ''}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Error al abrir el archivo")
    }
  }

  const handleRunOcr = async (documentId?: string) => {
    const targetDocumentId = documentId || activeDocumentId
    const targetDoc = targetDocumentId ? docIdToDocRef.current.get(targetDocumentId) : null

    if (!targetDocumentId || !targetDoc?.path) {
      toast.error('Abre un PDF primero')
      return
    }

    const loadingToast = toast.loading(`Procesando OCR para ${targetDoc.name}...`)

    try {
      const result = await ocrPdf({ path: targetDoc.path })

      if (!result?.pages) throw new Error('La respuesta del servidor no es válida')

      setOcrResultsByDoc(prev => ({
        ...prev,
        [targetDocumentId]: result.pages
      }))

      setActiveOcrIdxByDoc(prev => ({
        ...prev,
        [targetDocumentId]: 0
      }))
      
      // Abrir el panel automáticamente si estaba cerrado y se ejecutó OCR
      if (!isSidebarOpen) {
        setIsSidebarOpen(true)
      }

      toast.success(result.summary || 'OCR completado', { id: loadingToast })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Error desconocido'
      toast.error(`Error OCR: ${msg}`, { id: loadingToast })
    }
  }

  const handleRunActiveOcr = () => {
    const fallbackDocumentId = activeDocumentId || Array.from(docIdToDocRef.current.keys()).at(-1)
    void handleRunOcr(fallbackDocumentId)
  }

  const activeDocument = activeDocumentId ? docIdToDocRef.current.get(activeDocumentId) : null

  const copyToClipboard = () => {
    const text = ocrPages[activeOcrIdx]?.text
    if (text) {
      navigator.clipboard.writeText(text)
      toast.success('Texto copiado al portapapeles')
    }
  }

  const handleViewerReady = (registry: PluginRegistry) => {
    registryRef.current = registry
  }

  return (
    <div className="flex h-full w-full flex-col gap-4 p-4 lg:flex-row lg:gap-5 bg-slate-100/50 box-border overflow-hidden">
      <Toaster position="top-right" />

      <main className="flex flex-1 min-h-0 flex-col lg:flex-row gap-4 lg:gap-5">

        {/* === SECCIÓN DEL VISOR PDF === */}
        <section className="flex flex-col flex-1 min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">

          <header className="shrink-0 border-b border-slate-100 bg-slate-50/50 px-4 py-3 flex justify-between items-center z-10 flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
              <h2 className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                Gestor de Documentos
              </h2>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              
              {/* BOTÓN PARA OCULTAR/MOSTRAR PANEL OCR */}
              <button
                type="button"
                onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all shadow-sm ${
                  isSidebarOpen 
                    ? 'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 hover:border-blue-300' 
                    : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-50'
                }`}
                title={isSidebarOpen ? "Ocultar panel de resultados" : "Mostrar panel de resultados"}
              >
                <span>{isSidebarOpen ? '▶' : '◀'}</span> 
                {isSidebarOpen ? 'Ocultar OCR' : 'Mostrar OCR'}
              </button>

              <button
                type="button"
                onClick={handleRunActiveOcr}
                disabled={!hasOpenDocuments}
                className="flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-sm transition-all hover:bg-slate-50 hover:shadow disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:shadow-sm"
              >
                <span>👁️</span> Procesar OCR
              </button>
              <button
                type="button"
                onClick={handleOpen}
                className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-bold text-white shadow-sm transition-all hover:bg-blue-700 hover:shadow"
              >
                <span>+</span> Abrir PDF
              </button>
            </div>
          </header>

          <div className="relative flex-1 min-h-0 w-full overflow-hidden bg-slate-200/40">
            <PDFViewer
              ref={viewerRef}
              onReady={handleViewerReady}
              config={{
                tabBar: 'multiple',
                theme: { preference: themePreference },
                disabledCategories: ['document-open', 'document-close'],
                documentManager: { maxDocuments: 2 },
                i18n: { defaultLocale: 'es' }
              }}
              style={{ width: '100%', height: '100%', display: 'block' }}
            />
          </div>
        </section>

        {/* === SECCIÓN DE BARRA LATERAL OCR (CONDICIONAL) === */}
        {isSidebarOpen && (
          <aside className="flex flex-col shrink-0 w-full lg:w-[380px] h-[40vh] lg:h-full min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-4 shadow-sm animate-in fade-in slide-in-from-right-4 duration-300">
            
            <header className="shrink-0 flex items-center justify-between mb-4">
              <h3 className="text-xs font-extrabold text-slate-800 truncate pr-2 uppercase tracking-wide">
                Resultado OCR {activeDocument?.name ? `· ${activeDocument.name}` : ''}
              </h3>
              {ocrPages.length > 0 && (
                <button
                  onClick={copyToClipboard}
                  className="rounded px-2 py-1 text-[11px] font-semibold text-blue-600 transition hover:bg-blue-50"
                >
                  Copiar todo
                </button>
              )}
            </header>

            {!activeDocumentId ? (
              <div className="flex flex-1 min-h-0 items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 p-6 text-center text-xs text-slate-500">
                Abre un documento para ver los resultados del reconocimiento de texto.
              </div>
            ) : ocrPages.length === 0 ? (
              <div className="flex flex-1 min-h-0 items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 p-6 text-center text-xs text-slate-500">
                Aún no hay datos. Haz clic en <strong className="mx-1 text-slate-700">"Procesar OCR"</strong> en la barra superior.
              </div>
            ) : (
              <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
                <div className="shrink-0 mb-3 flex flex-wrap gap-1.5 overflow-y-auto max-h-32 pr-2 custom-scrollbar">
                  {ocrPages.map((p, idx) => (
                    <button
                      key={p.pageNumber}
                      onClick={() => setActiveOcrIdx(idx)}
                      className={`h-8 w-10 shrink-0 rounded-md text-[11px] font-bold transition-all border ${
                        activeOcrIdx === idx
                          ? 'border-blue-600 bg-blue-600 text-white shadow-md'
                          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      {p.pageNumber}
                    </button>
                  ))}
                </div>

                <div className="shrink-0 mb-3 flex items-center justify-between text-[10px] font-mono font-semibold text-slate-500 bg-slate-100/50 px-3 py-2 rounded-lg border border-slate-100">
                  <span className="uppercase">Modo: {ocrPages[activeOcrIdx]?.mode}</span>
                  <span className="uppercase">Origen: {ocrPages[activeOcrIdx]?.usedOcr ? 'Proceso OCR' : 'Nativo'}</span>
                </div>

                <textarea
                  readOnly
                  value={ocrPages[activeOcrIdx]?.text ?? ''}
                  className="flex-1 min-h-0 h-full w-full overflow-y-auto resize-none rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 custom-scrollbar shadow-inner"
                />
              </div>
            )}
          </aside>
        )}

      </main>
    </div>
  )
}