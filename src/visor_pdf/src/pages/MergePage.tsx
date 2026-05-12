import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { mergePdfs, pickFiles, openPdf, openPageThumb, pickDirectory } from '../services/api'
import toast, { Toaster } from 'react-hot-toast'
import { useAppState } from '../state/AppContext'

type FileItem = { path: string; name: string; pageCount?: number; dataUrl?: string; thumbDataUrls?: string[]; selected?: boolean[] }

export function MergePage() {
  const navigate = useNavigate()
  const [paths, setPaths] = useState<FileItem[]>([])
  const [outputPath, setOutputPath] = useState<string | null>(null)
  const [message, setMessage] = useState('Sin páginas seleccionadas')
  const { setCurrentPdf } = useAppState()

  const [modalOpen, setModalOpen] = useState(false)
  const [modalIndex, setModalIndex] = useState(0)
  const [isRunning, setIsRunning] = useState(false)
  const [modalThumbs, setModalThumbs] = useState<Record<string, string>>({})
  const THUMBS_PER_PAGE = 9
  const [thumbPage, setThumbPage] = useState<Record<string, number>>({})

  const selectedPreviewItems = (() => {
    const out: Array<{ key: string; thumb: string; sourceName: string; sourcePage: number; sourcePath: string; resultPos: number }> = []
    let resultPos = 1
    for (const item of paths) {
      const total = item.pageCount ?? 0
      const sel = item.selected ?? Array.from({ length: total }, () => true)
      for (let idx = 0; idx < total; idx += 1) {
        if (!sel[idx]) continue
        out.push({
          key: `${item.path}-${idx}`,
          thumb: item.thumbDataUrls?.[idx] ?? '',
          sourceName: item.name,
          sourcePage: idx + 1,
          sourcePath: item.path,
          resultPos,
        })
        resultPos += 1
      }
    }
    return out
  })()

  useEffect(() => {
    if (!modalOpen) return
    const item = selectedPreviewItems[modalIndex]
    if (!item) return
    const key = item.key
    if (modalThumbs[key]) return
    // request a higher-resolution thumbnail for the page (scale 1.8)
    ;(async () => {
      try {
        const res = await openPageThumb(item.sourcePath, item.sourcePage - 1, 1.8)
        if (res?.thumbDataUrl) {
          setModalThumbs((prev) => ({ ...prev, [key]: res.thumbDataUrl }))
        }
      } catch (_err) {
        // ignore errors, keep using small thumb
      }
    })()
  }, [modalOpen, modalIndex])

  const handleAdd = async () => {
    const files = await pickFiles({ multiple: true, title: 'Seleccionar PDFs para combinar' })
    if (files.length) {
      const loadingToast = toast.loading('Cargando archivos...')
      const items: FileItem[] = []
      
      for (const p of files) {
        try {
          const info = await openPdf(p)
          const pc = info?.pageCount ?? 0
          items.push({
            path: p,
            name: info?.name ?? p.split(/\\|\//).pop() ?? p,
            pageCount: pc,
            dataUrl: info?.dataUrl,
            thumbDataUrls: info?.thumbDataUrls ?? [],
            selected: Array.from({ length: pc }, () => true),
          })
        } catch (_) {
          items.push({ path: p, name: p.split(/\\|\//).pop() ?? p, thumbDataUrls: [], selected: [] })
        }
      }
      
      setPaths((prev) => {
        const existing = new Map(prev.map((it) => [it.path, it]))
        for (const it of items) existing.set(it.path, it)
        const out = Array.from(existing.values())
        setThumbPage((tp) => {
          const copy = { ...tp }
          for (const it of out) {
            if (!(it.path in copy)) copy[it.path] = 0
          }
          return copy
        })
        return out
      })
      toast.success(`${items.length} archivo(s) agregado(s)`, { id: loadingToast })
    }
  }

  const handleClear = () => {
    if (paths.length === 0) return
    if (!window.confirm('¿Seguro que deseas limpiar la lista de PDFs?')) return
    setPaths([])
    setOutputPath(null)
    setMessage('Sin páginas seleccionadas')
  }

  const handleMerge = async () => {
    const pages: Record<string, number[]> = {}
    for (const it of paths) {
      const sel = it.selected ?? []
      if (sel.length === 0) continue
      const allTrue = sel.every(Boolean)
      if (!allTrue) {
        pages[it.path] = sel.map((v, i) => v ? i : -1).filter((i) => i >= 0)
      }
    }

    setIsRunning(true)
    const loadingToast = toast.loading('Combinando PDFs...')
    
    try {
      const result = await mergePdfs({ paths: paths.map((p) => p.path), pages, outputPath })
      if (!result) throw new Error('Error desconocido al combinar PDFs')
      
      setOutputPath(result.outputPath ?? null)
      setMessage(result.message || 'Proceso finalizado')
      
      if (result.outputPath) {
        toast.success('PDF combinado creado correctamente', { id: loadingToast })
      } else {
        toast.error(result.message ?? 'Error al crear PDF', { id: loadingToast })
      }
    } catch (err: any) {
      toast.error(`Error al combinar: ${err?.message ?? String(err)}`, { id: loadingToast })
    } finally {
      setIsRunning(false)
    }
  }

  const handlePickDirectory = async () => {
    const dir = await pickDirectory('Selecciona carpeta de destino')
    if (dir) {
      setOutputPath(dir)
      const name = dir.split(/\\|\//).pop() || dir
      toast.success(`Carpeta destino: ${name}`)
    }
  }

  const handleOpenResult = async () => {
    if (!outputPath) {
      toast.error('No hay resultado para abrir')
      return
    }
    const result = await openPdf(outputPath)
    if (result) {
      setCurrentPdf(result)
      navigate('/ocr')
    }
  }

  return (
    // h-full w-full respeta la envoltura flex-1 de App.tsx
    <div className="flex h-full w-full flex-col gap-4 p-4 lg:flex-row lg:gap-5 bg-slate-100/50 box-border overflow-hidden">
      <Toaster position="top-right" />
      
      {/* SECCIÓN IZQUIERDA: Lista de PDFs a combinar */}
      <section className="flex flex-col flex-1 min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        
        {/* Cabecera fija */}
        <header className="shrink-0 flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 bg-slate-50/50 px-5 py-4">
          <h2 className="text-sm font-bold uppercase tracking-wide text-slate-800">Archivos Fuente</h2>
          <div className="flex gap-3">
            <button 
              type="button" 
              onClick={handleClear} 
              disabled={paths.length === 0}
              className="text-xs font-bold text-red-500 hover:text-red-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              Limpiar todo
            </button>
            <button
              type="button"
              onClick={handleAdd}
              className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 hover:shadow"
            >
              + Agregar PDF
            </button>
          </div>
        </header>

        {/* Lista de archivos con Scroll interno */}
        <div className="flex-1 min-h-0 overflow-y-auto p-5 custom-scrollbar bg-slate-50/30">
          {paths.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50 p-10 text-center text-xs text-slate-500">
              <div className="grid h-12 w-12 place-items-center rounded-xl border border-slate-200 bg-white text-slate-400 text-xl shadow-sm">
                📄
              </div>
              <p>Arrastra archivos o haz clic en <strong>"+ Agregar PDF"</strong> para comenzar a combinarlos.</p>
            </div>
          )}
          
          <div className="flex flex-col gap-4">
            {paths.map((item) => (
              <div key={item.path} className="rounded-xl border border-slate-200 bg-white shadow-sm p-4 transition-all hover:border-slate-300">
                <div className="flex items-start gap-3">
                  <div className="flex-1 text-xs">
                    <div className="font-bold text-slate-800 break-all">{item.name}</div>
                    
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <div className="flex overflow-hidden rounded-md border border-slate-300 bg-slate-50 text-[10px] font-semibold text-slate-600">
                        <button
                          type="button"
                          onClick={() => setPaths((prev) => prev.map((p) => p.path === item.path ? { ...p, selected: Array.from({ length: p.pageCount ?? 0 }, () => true) } : p))}
                          className="px-2.5 py-1.5 transition hover:bg-slate-200"
                        >
                          Todas
                        </button>
                        <div className="w-px bg-slate-300"></div>
                        <button
                          type="button"
                          onClick={() => setPaths((prev) => prev.map((p) => p.path === item.path ? { ...p, selected: Array.from({ length: p.pageCount ?? 0 }, () => false) } : p))}
                          className="px-2.5 py-1.5 transition hover:bg-slate-200"
                        >
                          Ninguna
                        </button>
                        <div className="w-px bg-slate-300"></div>
                        <button
                          type="button"
                          onClick={() => setPaths((prev) => prev.map((p) => p.path === item.path ? { ...p, selected: (p.selected ?? []).map((v) => !v) } : p))}
                          className="px-2.5 py-1.5 transition hover:bg-slate-200"
                        >
                          Invertir
                        </button>
                      </div>
                      <span className="text-[11px] font-medium text-slate-500 bg-slate-100 px-2 py-1 rounded-md">
                        {(item.selected ?? []).filter(Boolean).length} de {item.pageCount ?? 0} págs.
                      </span>
                    </div>
                  </div>
                  
                  {/* Botones de ordenamiento y eliminación */}
                  <div className="flex flex-col items-center gap-1 rounded-lg border border-slate-100 bg-slate-50 p-1">
                    <button type="button" title="Mover arriba" onClick={() => { setPaths(prev => { const idx = prev.findIndex(p => p.path === item.path); if (idx <= 0) return prev; const copy = prev.slice(); [copy[idx-1], copy[idx]] = [copy[idx], copy[idx-1]]; return copy }) }} className="h-6 w-6 rounded flex items-center justify-center text-[#6b7280] hover:bg-slate-200 transition">↑</button>
                    <button type="button" title="Mover abajo" onClick={() => { setPaths(prev => { const idx = prev.findIndex(p => p.path === item.path); if (idx < 0 || idx === prev.length - 1) return prev; const copy = prev.slice(); [copy[idx+1], copy[idx]] = [copy[idx], copy[idx+1]]; return copy }) }} className="h-6 w-6 rounded flex items-center justify-center text-[#6b7280] hover:bg-slate-200 transition">↓</button>
                    <button type="button" title="Eliminar" onClick={() => { setPaths(prev => prev.filter(p => p.path !== item.path)) }} className="h-6 w-6 rounded flex items-center justify-center text-red-500 hover:bg-red-100 transition">🗑</button>
                  </div>
                </div>

                <div className="mt-4 pt-4 border-t border-slate-100">
                  {/* Grid de Thumbnails */}
                  <div className="flex flex-col gap-2">
                    {(() => {
                      const total = item.pageCount ?? 0
                      const per = THUMBS_PER_PAGE
                      const pagesToShow = (thumbPage[item.path] ?? 0) + 1
                      const rows = [] as any[]
                      for (let p = 0; p < pagesToShow; p += 1) {
                        const start = p * per
                        const end = Math.min(start + per, total)
                        const row = (
                          <div key={`row-${p}`} className="flex flex-wrap gap-2">
                            {Array.from({ length: end - start }).map((_, i) => {
                              const idx = start + i
                              const selected = item.selected ? item.selected[idx] : false
                              const thumb = item.thumbDataUrls?.[idx] ?? ''
                              return (
                                <button
                                  key={idx}
                                  title={`Doble clic para previsualizar página ${idx + 1}`}
                                  onClick={() => {
                                    setPaths((prev) =>
                                      prev.map((q) => {
                                        if (q.path !== item.path) return q
                                        const sel = (q.selected ?? Array.from({ length: q.pageCount ?? 0 }, () => true)).slice()
                                        sel[idx] = !sel[idx]
                                        return { ...q, selected: sel }
                                      }),
                                    )
                                  }}
                                  onDoubleClick={() => {
                                    const orderedIndex = selectedPreviewItems.findIndex(
                                      (p2) => p2.sourceName === item.name && p2.sourcePage === idx + 1,
                                    )
                                    if (orderedIndex >= 0) {
                                      setModalIndex(orderedIndex)
                                      setModalOpen(true)
                                    }
                                  }}
                                  className={`relative h-[72px] w-[54px] sm:h-[90px] sm:w-[68px] flex-shrink-0 overflow-hidden rounded-md border-2 transition-all ${selected ? 'border-green-500 bg-green-50 shadow-sm scale-100' : 'border-slate-200 bg-slate-100 opacity-60 scale-95 hover:opacity-100'}`}
                                >
                                  {thumb ? (
                                    <img src={thumb} alt={`${item.name} p${idx + 1}`} className="mx-auto h-full w-auto object-contain" />
                                  ) : (
                                    <div className="flex h-full w-full items-center justify-center text-[10px] font-bold text-slate-400">P{idx + 1}</div>
                                  )}
                                  
                                  {/* Indicador de selección */}
                                  {selected && (
                                    <div className="absolute top-1 right-1 h-3 w-3 rounded-full bg-green-500 border border-white shadow-sm flex items-center justify-center">
                                      <span className="text-[8px] text-white font-bold leading-none">✓</span>
                                    </div>
                                  )}
                                  <span className={`absolute bottom-0 left-0 right-0 py-0.5 text-center text-[9px] font-bold text-white ${selected ? 'bg-green-600/90' : 'bg-slate-700/60'}`}>{idx + 1}</span>
                                </button>
                              )
                            })}
                          </div>
                        )
                        rows.push(row)
                      }
                      return rows
                    })()}

                    {/* Botones de Paginación de Thumbnails */}
                    {(() => {
                      const total = item.pageCount ?? 0
                      const per = THUMBS_PER_PAGE
                      const pages = Math.ceil(total / per)
                      const cur = (thumbPage[item.path] ?? 0) + 1
                      return (
                        <div className="mt-2 flex gap-2">
                          {cur > 1 && (
                            <button
                              type="button"
                              onClick={() => setThumbPage((tp) => ({ ...tp, [item.path]: Math.max(0, (tp[item.path] ?? 0) - 1) }))}
                              className="px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-[11px] font-semibold text-slate-600 hover:bg-slate-50 transition"
                            >
                              Mostrar menos
                            </button>
                          )}
                          {cur < pages && (
                            <button
                              type="button"
                              onClick={() => setThumbPage((tp) => ({ ...tp, [item.path]: (tp[item.path] ?? 0) + 1 }))}
                              className="px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-[11px] font-semibold text-slate-600 hover:bg-slate-50 transition"
                            >
                              Cargar más ({cur}/{pages})
                            </button>
                          )}
                        </div>
                      )
                    })()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SECCIÓN DERECHA: Vista previa del resultado y Acciones */}
      <aside className="flex flex-col w-full lg:w-[340px] shrink-0 min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="shrink-0 text-sm font-bold uppercase tracking-wide text-slate-800 mb-4">Resultado Esperado</h3>
        
        {/* Contenedor flexible para las miniaturas del resultado */}
        <div className="flex-1 min-h-0 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-3 custom-scrollbar shadow-inner mb-4">
          {selectedPreviewItems.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-xs text-slate-400">
              <div className="grid h-12 w-12 place-items-center rounded-xl border-2 border-dashed border-slate-300 bg-white text-xl">
                🔗
              </div>
              <p className="text-center px-4">Selecciona páginas de los PDFs para ver cómo quedará el documento final.</p>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {selectedPreviewItems.map((it, idx) => (
                <button
                  key={it.key}
                  type="button"
                  className="relative overflow-hidden rounded-md border border-slate-300 bg-white shadow-sm transition hover:border-blue-500 hover:shadow-md"
                  title={`${it.sourceName} — pág ${it.sourcePage} — pos ${it.resultPos}`}
                  onClick={() => {
                    setModalIndex(idx)
                    setModalOpen(true)
                  }}
                >
                  {it.thumb ? (
                    <img src={it.thumb} alt={`${it.sourceName} p${it.sourcePage}`} className="h-24 w-full object-cover" />
                  ) : (
                    <div className="flex h-24 w-full items-center justify-center bg-slate-100 text-[10px] font-bold text-slate-400">P{it.sourcePage}</div>
                  )}
                  <div className="absolute bottom-0 left-0 right-0 bg-blue-900/80 px-1 py-0.5 text-center text-[10px] font-bold text-white backdrop-blur-sm">
                    {it.resultPos}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        
        {/* Acciones Finales (Siempre visibles abajo) */}
        <div className="shrink-0 flex flex-col gap-3">
          <div className="flex justify-between items-center text-[11px] font-bold text-slate-500 uppercase tracking-wider bg-slate-100 px-3 py-1.5 rounded-lg border border-slate-200">
            <span>Páginas finales:</span>
            <span className="text-blue-600 text-[13px]">{selectedPreviewItems.length}</span>
          </div>

          <div className="flex items-center gap-2 mt-2">
            <div className="flex-1 rounded-lg border border-slate-300 bg-slate-50 px-3 py-2.5 truncate text-[11px] font-medium text-slate-700" title={outputPath || ''}>
              {outputPath ? outputPath.split(/\\|\//).pop() || outputPath : 'Selecciona carpeta de destino...'}
            </div>
            <button
              type="button"
              onClick={handlePickDirectory}
              className="flex-shrink-0 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-[11px] font-bold text-slate-700 transition hover:bg-slate-50 hover:shadow-sm"
            >
              Examinar
            </button>
          </div>
          
          <button
            type="button"
            onClick={handleMerge}
            disabled={isRunning || selectedPreviewItems.length === 0}
            className={`flex justify-center items-center gap-2 rounded-lg py-3 text-xs font-bold text-white shadow-sm transition-all ${
              isRunning || selectedPreviewItems.length === 0 
                ? 'bg-slate-400 cursor-not-allowed' 
                : 'bg-blue-600 hover:bg-blue-700 hover:shadow'
            }`}
          >
            {isRunning ? (
              <><span className="animate-spin text-sm">⚙️</span> Procesando...</>
            ) : (
              <><span className="text-sm">📥</span> Combinar y Guardar</>
            )}
          </button>
          
          <button
            type="button"
            onClick={handleOpenResult}
            disabled={!outputPath}
            className="rounded-lg border border-slate-300 bg-white py-2.5 text-xs font-bold text-slate-700 transition-all hover:bg-slate-50 disabled:bg-slate-50 disabled:text-slate-400 disabled:border-slate-200 disabled:cursor-not-allowed"
          >
            Abrir archivo resultante
          </button>
        </div>
      </aside>

      {/* MODAL DE VISTA PREVIA (Mantenido casi igual, retoques visuales) */}
      {modalOpen && selectedPreviewItems.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-sm p-4">
          <div className="flex flex-col w-full max-w-[800px] max-h-[90vh] overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-4">
              <h3 className="text-sm font-bold uppercase tracking-wide text-slate-800">
                Vista Previa de Página
              </h3>
              <button
                onClick={() => setModalOpen(false)}
                className="rounded-lg bg-slate-200 px-4 py-1.5 text-xs font-bold text-slate-700 transition hover:bg-slate-300"
              >
                Cerrar ✕
              </button>
            </div>
            
            <div className="flex-1 min-h-0 flex items-center justify-between gap-4 p-5 overflow-hidden">
              <button
                type="button"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-slate-300 bg-white text-slate-600 shadow-sm transition hover:bg-slate-50 disabled:opacity-30 disabled:hover:bg-white"
                onClick={() => setModalIndex((prev) => Math.max(0, prev - 1))}
                disabled={modalIndex <= 0}
              >
                ◀
              </button>
              
              <div className="flex-1 h-full min-h-0 rounded-xl border border-slate-200 bg-slate-100 p-2 overflow-auto custom-scrollbar flex items-center justify-center">
                {(() => {
                  const cur = selectedPreviewItems[modalIndex]
                  const src = cur ? modalThumbs[cur.key] ?? cur.thumb : ''
                  if (src) {
                    return <img src={src} alt={`${cur.sourceName} p${cur.sourcePage}`} className="max-h-full max-w-full object-contain drop-shadow-md" />
                  }
                  return <div className="text-sm font-semibold text-slate-400">Sin miniatura disponible</div>
                })()}
              </div>
              
              <button
                type="button"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-slate-300 bg-white text-slate-600 shadow-sm transition hover:bg-slate-50 disabled:opacity-30 disabled:hover:bg-white"
                onClick={() => setModalIndex((prev) => Math.min(selectedPreviewItems.length - 1, prev + 1))}
                disabled={modalIndex >= selectedPreviewItems.length - 1}
              >
                ▶
              </button>
            </div>
            
            <div className="border-t border-slate-100 bg-slate-50 px-5 py-4 text-xs text-slate-700 flex flex-wrap justify-between items-center gap-4">
              <div>
                <p><strong>Archivo original:</strong> {selectedPreviewItems[modalIndex]?.sourceName}</p>
                <p className="mt-1"><strong>Página original:</strong> {selectedPreviewItems[modalIndex]?.sourcePage}</p>
              </div>
              <div className="text-right">
                <span className="inline-block rounded-lg bg-blue-100 px-3 py-1.5 text-blue-800 font-bold border border-blue-200">
                  Página final: {selectedPreviewItems[modalIndex]?.resultPos} de {selectedPreviewItems.length}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
