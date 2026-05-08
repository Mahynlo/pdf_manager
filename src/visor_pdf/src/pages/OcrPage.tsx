import { PDFViewer } from '@embedpdf/react-pdf-viewer'
import type { PDFViewerRef } from '@embedpdf/react-pdf-viewer'
import { useEffect, useRef, useState } from 'react'
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

  useEffect(() => {
    if (!currentPdf || !registryRef.current) return
    if (openedDocPathsRef.current.has(currentPdf.path)) return

    const docMgr = registryRef.current.getPlugin('document-manager') as DocumentManagerCapability
    const docId = `doc-${++docIdCounterRef.current}`
    
    openedDocPathsRef.current.add(currentPdf.path)
    docIdToPathRef.current.set(docId, currentPdf.path)
    docIdToDocRef.current.set(docId, currentPdf)
    
    docMgr.openDocumentUrl({
      url: currentPdf.dataUrl,
      name: currentPdf.name,
      documentId: docId,
      autoActivate: true
    })

    setActiveDocumentId(docId)
  }, [currentPdf])

  useEffect(() => {
    if (!activeDocumentId) return
    const activeDoc = docIdToDocRef.current.get(activeDocumentId)
    if (activeDoc && currentPdf?.path !== activeDoc.path) {
      setCurrentPdf(activeDoc)
    }
  }, [activeDocumentId, currentPdf, setCurrentPdf])

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

      const docMgr = registryRef.current?.getPlugin('document-manager') as DocumentManagerCapability
      if (!docMgr) throw new Error('DocumentManager no disponible')

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
        
        docMgr.openDocumentUrl({
          url: doc.dataUrl,
          name: doc.name,
          documentId: docId,
          autoActivate: isLast
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
    
    try {
      const docMgr = registry.getPlugin('document-manager') as DocumentManagerCapability

      if (docMgr.onActiveDocumentChanged?.subscribe) {
        docMgr.onActiveDocumentChanged.subscribe(({ currentDocumentId }: { currentDocumentId: string }) => {
          setActiveDocumentId(currentDocumentId)
        })
      }

      if (docMgr.onDocumentOpened?.subscribe) {
        docMgr.onDocumentOpened.subscribe(({ documentId, name }: { documentId: string; name: string }) => {
          console.log(`📄 Documento abierto: ${name} (${documentId})`)
        })
      }

      if (docMgr.onDocumentClosed?.subscribe) {
        docMgr.onDocumentClosed.subscribe(({ documentId }: { documentId: string }) => {
          console.log(`❌ Documento cerrado: ${documentId}`)
          
          const path = docIdToPathRef.current.get(documentId)
          if (path) {
            openedDocPathsRef.current.delete(path)
            docIdToPathRef.current.delete(documentId)
          }
          
          setOcrResultsByDoc(prev => {
            const next = { ...prev }
            delete next[documentId]
            return next
          })
          setActiveOcrIdxByDoc(prev => {
            const next = { ...prev }
            delete next[documentId]
            return next
          })
          docIdToDocRef.current.delete(documentId)
        })
      }
    } catch (error) {
      console.warn('⚠️ Error configurando DocumentManager:', error)
    }
  }

  return (
    // 1. Contenedor Maestro: h-screen y overflow-hidden bloquean el scroll de la página completa
    <div className="flex h-screen w-full flex-col bg-slate-100 p-3 sm:p-5 font-sans overflow-hidden box-border">
      <Toaster position="top-right" />

      {/* 2. Main flex area: min-h-0 es crítico para que sus hijos no lo desborden */}
      <main className="flex flex-1 min-h-0 flex-col lg:flex-row gap-4 lg:gap-5">
        
        {/* === SECCIÓN DEL VISOR PDF === */}
        <section className="flex flex-col flex-1 min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          
          {/* Header Superior del Visor (Tamaño fijo, no se aplasta) */}
          <header className="shrink-0 border-b border-slate-100 bg-slate-50/50 px-4 py-3 flex justify-between items-center z-10">
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
              <h2 className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                Gestor de Documentos
              </h2>
            </div>
            <div className="flex items-center gap-2">
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

          {/* Contenedor estricto del visor PDF (min-h-0 previene el desbordamiento de Flexbox) */}
          <div className="relative flex-1 min-h-0 w-full overflow-hidden bg-slate-200/40">
            <PDFViewer
              ref={viewerRef}
              onReady={handleViewerReady}
              config={{
                tabBar: 'multiple',
                theme: { preference: themePreference },
                disabledCategories: ['document-open', 'document-close'],
                documentManager: { maxDocuments: 10 }
              }}
              // Bloquear el display block ayuda a ciertos iframes/canvas a no generar espacio residual abajo
              style={{ width: '100%', height: '100%', display: 'block' }}
            />
          </div>
        </section>

        {/* === SECCIÓN DE BARRA LATERAL OCR === */}
        {/* shrink-0 evita que flexbox la haga más delgada de lo necesario */}
        <aside className="flex flex-col shrink-0 w-full lg:w-[380px] h-[40vh] lg:h-full min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          
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
             <div className="flex flex-1  h-dvh items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 p-6 text-center text-xs text-slate-500">
               Abre un documento para ver los resultados del reconocimiento de texto.
             </div>
          ) : ocrPages.length === 0 ? (
            <div className="flex flex-1  h-dvh items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 p-6 text-center text-xs text-slate-500">
              Aún no hay datos. Haz clic en <strong className="mx-1 text-slate-700">"Procesar OCR"</strong> en la barra superior.
            </div>
          ) : (
            <div className="flex flex-col flex-1 h-dvh overflow-hidden">
              
              {/* Paginador limitando su altura máxima y con scroll */}
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

              {/* Área de texto que consume el resto del espacio disponible */}
              <textarea
                readOnly
                value={ocrPages[activeOcrIdx]?.text ?? ''}
                className="flex-1 min-h-0 h-full w-full overflow-y-auto resize-none rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 custom-scrollbar shadow-inner"
              />
            </div>
          )}
        </aside>

      </main>
    </div>
  )
}
