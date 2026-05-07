
import { useMemo, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { extractPdf, openPdf, pickDirectory, pickFiles } from '../services/api'
import toast, { Toaster } from 'react-hot-toast'
import { useAppState } from '../state/AppContext'

type LogEntry = {
  level: 'info' | 'warn' | 'error' | 'success'
  text: string
}

const levelStyles: Record<LogEntry['level'], string> = {
  info: 'text-[#5a6b7f]',
  warn: 'text-[#d97706]',
  error: 'text-[#dc2626]',
  success: 'text-[#16a34a]',
}

export function ExtractPage() {
  const navigate = useNavigate()
  const [referencePath, setReferencePath] = useState<string | null>(null)
  const [targetPaths, setTargetPaths] = useState<string[]>([])
  const [destinationDir, setDestinationDir] = useState<string | null>(null)
  const [referencePages, setReferencePages] = useState('')
  const [hintPages, setHintPages] = useState('')
  const [keywords, setKeywords] = useState('')
  const [summary, setSummary] = useState('Sin busqueda ejecutada')
  const [log, setLog] = useState<LogEntry[]>([])
  const [outputPath, setOutputPath] = useState<string | null>(null)
  const { setCurrentPdf } = useAppState()

  useEffect(() => {
    // Registrar callback global para recibir logs incrementales desde Python
    const anyWindow = window as any
    anyWindow.__app_on_log = (entry: LogEntry) => {
      // Añadir entrada incrementalmente
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


  const referenceLabel = useMemo(
    () => (referencePath ? `Referencia: ${referencePath.split('\\').pop()}` : 'Referencia: sin archivo'),
    [referencePath],
  )

  const handlePickReference = async () => {
    const files = await pickFiles({ multiple: false, title: 'Seleccionar PDF referencia' })
    if (files.length) {
      setReferencePath(files[0])
    }
  }

  const handlePickTargets = async () => {
    const files = await pickFiles({ multiple: true, title: 'Seleccionar PDFs objetivo' })
    if (files.length) {
      setTargetPaths(files)
      toast.success(`${files.length} archivo(s) cargado(s)`)
    }
  }

  const handlePickDestination = async () => {
    const dir = await pickDirectory('Seleccionar carpeta destino')
    if (dir) {
      setDestinationDir(dir)
      const name = (dir || '').split(/\\|\//).pop() || dir
      toast.success(`Carpeta destino seleccionada: ${name}`)
    }
  }

  const handleRun = async () => {
    // Validaciones básicas en frontend
    if (!targetPaths || targetPaths.length === 0) {
      const err: LogEntry = { level: 'error', text: 'Selecciona al menos un PDF objetivo.' }
      setSummary('Falta seleccionar PDFs objetivo.')
      setLog([err])
      return
    }

    if (!keywords || !keywords.trim()) {
      const err: LogEntry = { level: 'error', text: 'Introduce al menos una palabra clave para la búsqueda.' }
      setSummary('Faltan palabras clave.')
      setLog([err])
      return
    }

    setSummary('Ejecutando búsqueda...')
    setLog([])

    try {
      const result = await extractPdf({
        referencePath,
        referencePages,
        hintPages,
        keywords,
        targetPaths,
        destinationDir,
      })

      if (!result) {
        const err: LogEntry = { level: 'error', text: 'API no disponible.' }
        setSummary('Error: API no disponible')
        setLog([err])
        toast.error('API no disponible')
        return
      }

      setSummary(result.summary)
      setLog(result.log as LogEntry[])
      setOutputPath(result.outputPath ?? null)
      if (result.outputPath) {
        toast.success(result.summary ?? 'Extracción completada')
      } else {
        toast.error(result.summary ?? 'No se generó resultado')
      }
    } catch (ex: any) {
      const msg = ex?.message ? ex.message : String(ex)
      const err: LogEntry = { level: 'error', text: `Error ejecutando extracción: ${msg}` }
      setSummary('Error en la operación')
      setLog([err])
      toast.error(`Error: ${msg}`)
    }
  }

  const handlePreview = async () => {
    if (!outputPath) {
      toast.error('No hay resultado para previsualizar')
      return
    }
    const result = await openPdf(outputPath)
    if (!result) {
      return
    }
    setCurrentPdf(result)
    navigate('/ocr')
  }

  return (
    <div className="flex min-h-[calc(100vh-120px)] flex-col gap-6 px-6 py-6 lg:flex-row">
      <Toaster position="top-right" />
      <section className="w-full max-w-sm rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <h2 className="text-sm font-semibold text-[#0f1824]">Referencia</h2>
        <button
          type="button"
          onClick={handlePickReference}
          className="mt-4 rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]"
        >
          Abrir PDF referencia
        </button>
        <div className="mt-4 space-y-2 text-xs text-[#5a6b7f]">
          <p>{referenceLabel}</p>
          <p>Tipo: -</p>
        </div>
        <input
          value={referencePages}
          onChange={(event) => setReferencePages(event.target.value)}
          className="mt-4 w-full rounded-lg border border-[#d8dee8] bg-[#f7f9fc] px-3 py-2 text-xs"
          placeholder="Paginas de referencia (ej: 1,3-5)"
        />

        <div className="mt-6">
          <h3 className="text-xs font-semibold text-[#0f1824]">Patron de busqueda</h3>
          <textarea
            value={keywords}
            onChange={(event) => setKeywords(event.target.value)}
            className="mt-3 h-28 w-full rounded-lg border border-[#d8dee8] bg-[#f7f9fc] px-3 py-2 text-xs"
            placeholder="Palabras clave / titulos / nombres de formato"
          />
        </div>

        <div className="mt-6">
          <h3 className="text-xs font-semibold text-[#0f1824]">Opciones avanzadas</h3>
          <input
            value={hintPages}
            onChange={(event) => setHintPages(event.target.value)}
            className="mt-3 w-full rounded-lg border border-[#d8dee8] bg-[#f7f9fc] px-3 py-2 text-xs"
            placeholder="Pagina sugerida en cada objetivo (ej: 1,2)"
          />
        </div>
      </section>

      <section className="flex-1 rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-sm font-semibold text-[#0f1824]">Objetivos y extraccion</h2>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={handlePickTargets}
              className="rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]"
            >
              Cargar PDFs objetivo
            </button>
            <button
              type="button"
              onClick={handlePickDestination}
              className="rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]"
            >
              Carpeta destino
            </button>
          </div>
        </div>
        <div className="mt-4 space-y-2 text-xs text-[#5a6b7f]">
          <p>Archivos objetivo: {targetPaths.length}</p>
          <p>Destino: {destinationDir ?? 'sin definir'}</p>
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleRun}
            className="flex items-center gap-2 rounded-full bg-[#365b89] px-5 py-2 text-xs font-semibold text-white shadow-sm"
          >
            Buscar y extraer
          </button>
          <button
            type="button"
            onClick={handlePreview}
            className="rounded-full border border-[#cfd7e2] px-5 py-2 text-xs font-semibold text-[#9aa6b2]"
          >
            Abrir vista previa
          </button>
        </div>
        <div className="mt-6 text-xs text-[#5a6b7f]">{summary}</div>
        <div className="mt-5">
          <h3 className="text-xs font-semibold text-[#0f1824]">Registro de operacion</h3>
          <div className="mt-2 h-60 overflow-auto rounded-xl border border-[#d8dee8] bg-white p-3 text-xs">
            {log.length === 0 && <p className="text-[#9aa6b2]">Sin registros</p>}
            {log.map((entry, idx) => (
              <p key={`${entry.text}-${idx}`} className={levelStyles[entry.level]}>
                {entry.text}
              </p>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
