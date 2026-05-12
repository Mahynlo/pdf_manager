import { useMemo, useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { extractPdf, openPdf, pickDirectory, pickFiles } from '../services/api'
import toast, { Toaster } from 'react-hot-toast'
import { useAppState } from '../state/AppContext'

type LogEntry = {
  level: 'info' | 'warn' | 'error' | 'success'
  text: string
}

const levelStyles: Record<LogEntry['level'], string> = {
  info: 'text-slate-500',
  warn: 'text-amber-600',
  error: 'text-red-600',
  success: 'text-green-600',
}

export function ExtractPage() {
  const navigate = useNavigate()
  const { setCurrentPdf } = useAppState()
  
  // Referencias para auto-scroll de logs
  const logContainerRef = useRef<HTMLDivElement>(null)
  
  // Estados de archivos
  const [referencePath, setReferencePath] = useState<string | null>(null)
  const [targetPaths, setTargetPaths] = useState<string[]>([])
  const [destinationDir, setDestinationDir] = useState<string | null>(null)
  const [outputPath, setOutputPath] = useState<string | null>(null)
  
  // Estados de formulario
  const [referencePages, setReferencePages] = useState('')
  const [hintPages, setHintPages] = useState('')
  const [keywords, setKeywords] = useState('')
  
  // Estados de UI
  const [isExtracting, setIsExtracting] = useState(false)
  const [summary, setSummary] = useState('Sin búsqueda ejecutada')
  const [log, setLog] = useState<LogEntry[]>([])

  // Registrar callback global para recibir logs incrementales desde Python
  useEffect(() => {
    const anyWindow = window as any
    anyWindow.__app_on_log = (entry: LogEntry) => {
      setLog((prev) => [...prev, entry])
    }
    return () => {
      try {
        delete anyWindow.__app_on_log
      } catch (_) {
        /* ignore */
      }
    }
  }, [])

  // Auto-scroll para los logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [log])

  const referenceLabel = useMemo(
    () => (referencePath ? `Archivo: ${referencePath.split('\\').pop()?.split('/').pop()}` : 'Sin archivo seleccionado'),
    [referencePath],
  )

  const handlePickReference = async () => {
    const files = await pickFiles({ multiple: false, title: 'Seleccionar PDF referencia' })
    if (files?.length) {
      setReferencePath(files[0])
    }
  }

  const handlePickTargets = async () => {
    const files = await pickFiles({ multiple: true, title: 'Seleccionar PDFs objetivo' })
    if (files?.length) {
      setTargetPaths(files)
      toast.success(`${files.length} archivo(s) cargado(s)`)
    }
  }

  const handlePickDestination = async () => {
    const dir = await pickDirectory('Seleccionar carpeta destino')
    if (dir) {
      setDestinationDir(dir)
      const name = dir.split(/\\|\//).pop() || dir
      toast.success(`Carpeta destino: ${name}`)
    }
  }

  const handleRun = async () => {
    if (!targetPaths || targetPaths.length === 0) {
      setSummary('Falta seleccionar PDFs objetivo.')
      setLog([{ level: 'error', text: 'Selecciona al menos un PDF objetivo.' }])
      return
    }

    if (!keywords || !keywords.trim()) {
      setSummary('Faltan palabras clave.')
      setLog([{ level: 'error', text: 'Introduce al menos una palabra clave para la búsqueda.' }])
      return
    }

    setIsExtracting(true)
    setSummary('Ejecutando extracción...')
    setLog([])
    setOutputPath(null)
    const loadingToast = toast.loading('Extrayendo información...')

    try {
      const result = await extractPdf({
        referencePath,
        referencePages,
        hintPages,
        keywords,
        targetPaths,
        destinationDir,
      })

      if (!result) throw new Error('API no disponible o sin respuesta.')

      setSummary(result.summary)
      // Si la API mandó logs de golpe, los agregamos
      if (result.log && result.log.length > 0) {
        setLog((prev) => [...prev, ...(result.log as LogEntry[])])
      }
      
      setOutputPath(result.outputPath ?? null)
      
      if (result.outputPath) {
        toast.success(result.summary ?? 'Extracción completada', { id: loadingToast })
      } else {
        toast.error(result.summary ?? 'No se generó ningún resultado', { id: loadingToast })
      }
    } catch (ex: any) {
      const msg = ex?.message || String(ex)
      setSummary('Error en la operación')
      setLog((prev) => [...prev, { level: 'error', text: `Error: ${msg}` }])
      toast.error(`Error: ${msg}`, { id: loadingToast })
    } finally {
      setIsExtracting(false)
    }
  }

  const handlePreview = async () => {
    if (!outputPath) return
    const result = await openPdf(outputPath)
    if (!result) return
    
    setCurrentPdf(result)
    navigate('/ocr') // O la ruta de tu visor principal
  }

  return (
    // h-full y min-h-0 para respetar el layout global
    <div className="flex h-full w-full flex-col gap-4 p-4 lg:flex-row lg:gap-5 overflow-hidden bg-slate-100/50 box-border">
      <Toaster position="top-right" />
      
      {/* SECCIÓN IZQUIERDA: Configuración (Ancho fijo en PC, scrollable internamente si es necesario) */}
      <aside className="flex flex-col w-full lg:w-[360px] shrink-0 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-sm custom-scrollbar">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-800">Referencia y Búsqueda</h2>
        
        <div className="mt-5 rounded-xl border border-slate-100 bg-slate-50 p-4">
          <button
            type="button"
            onClick={handlePickReference}
            className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-sm transition-all hover:bg-slate-50 hover:shadow"
          >
            Abrir PDF referencia
          </button>
          <div className="mt-3 space-y-1 text-[11px] text-slate-500 font-medium">
            <p className="truncate" title={referenceLabel}>{referenceLabel}</p>
          </div>
          <input
            value={referencePages}
            onChange={(event) => setReferencePages(event.target.value)}
            className="mt-3 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="Páginas (ej: 1, 3-5)"
          />
        </div>

        <div className="mt-5">
          <h3 className="text-xs font-bold text-slate-700 mb-2">Patrón de búsqueda *</h3>
          <textarea
            value={keywords}
            onChange={(event) => setKeywords(event.target.value)}
            className="h-28 w-full resize-none rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 custom-scrollbar"
            placeholder="Palabras clave, títulos o nombres de formato separados por comas..."
          />
        </div>

        <div className="mt-5 mb-2">
          <h3 className="text-xs font-bold text-slate-700 mb-2">Opciones avanzadas</h3>
          <input
            value={hintPages}
            onChange={(event) => setHintPages(event.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="Página sugerida en objetivos (ej: 1, 2)"
          />
        </div>
      </aside>

      {/* SECCIÓN DERECHA: Objetivos y Logs (Se estira para llenar el espacio, min-h-0 crucial) */}
      <section className="flex flex-col flex-1 min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        
        <header className="shrink-0 flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
          <div>
            <h2 className="text-sm font-bold uppercase tracking-wide text-slate-800">Objetivos y Extracción</h2>
            <p className="text-[11px] font-medium text-slate-500 mt-1">
              Archivos: {targetPaths.length} | Destino: <span className="truncate max-w-[150px] inline-block align-bottom" title={destinationDir || ''}>{destinationDir ? destinationDir.split(/\\|\//).pop() : 'No definido'}</span>
            </p>
          </div>
          
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handlePickTargets}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 transition hover:bg-slate-50"
            >
              + Cargar Objetivos
            </button>
            <button
              type="button"
              onClick={handlePickDestination}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 transition hover:bg-slate-50"
            >
              Carpeta Destino
            </button>
          </div>
        </header>

        {/* Acciones principales */}
        <div className="shrink-0 mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleRun}
            disabled={isExtracting}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-2 text-xs font-bold text-white shadow-sm transition-all hover:bg-blue-700 hover:shadow disabled:bg-slate-400 disabled:cursor-not-allowed"
          >
            {isExtracting ? (
              <>
                <span className="animate-spin">⚙️</span> Procesando...
              </>
            ) : (
              <>
                <span>▶</span> Buscar y Extraer
              </>
            )}
          </button>
          <button
            type="button"
            onClick={handlePreview}
            disabled={!outputPath || isExtracting}
            className="rounded-lg border border-slate-300 bg-white px-5 py-2 text-xs font-bold text-slate-700 transition-all hover:bg-slate-50 disabled:border-slate-200 disabled:text-slate-400 disabled:bg-slate-50 disabled:cursor-not-allowed"
          >
            Abrir vista previa
          </button>
          <span className="ml-auto text-[11px] font-semibold text-blue-600 bg-blue-50 px-3 py-1 rounded-full">
            {summary}
          </span>
        </div>

        {/* Consola de Logs (Toma el resto del espacio vertical) */}
        <div className="mt-5 flex flex-col flex-1 min-h-0">
          <h3 className="shrink-0 text-xs font-bold text-slate-700 mb-2">Registro de operación</h3>
          <div 
            ref={logContainerRef}
            className="flex-1 min-h-0 overflow-y-auto rounded-xl border border-slate-200 bg-slate-900 p-4 font-mono text-[11px] shadow-inner custom-scrollbar"
          >
            {log.length === 0 ? (
              <p className="text-slate-500 italic">🚩Esperando iniciar proceso...</p>
            ) : (
              log.map((entry, idx) => (
                <p key={`${entry.text}-${idx}`} className={`mb-1 leading-relaxed ${levelStyles[entry.level]}`}>
                  <span className="opacity-50 mr-2">{'>'}</span>{entry.text}
                </p>
              ))
            )}
          </div>
        </div>

      </section>
    </div>
  )
}
