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
  const [message, setMessage] = useState('Sin paginas seleccionadas')
  const { setCurrentPdf } = useAppState()

  const [modalOpen, setModalOpen] = useState(false)
  const [modalIndex, setModalIndex] = useState(0)
  const [isRunning, setIsRunning] = useState(false)
  const [modalThumbs, setModalThumbs] = useState<Record<string, string>>({})
  const THUMBS_PER_PAGE = 9
  const [thumbPage, setThumbPage] = useState<Record<string, number>>({})

  const selectedPreviewItems: Array<{
    key: string
    thumb: string
    sourceName: string
    sourcePage: number
    sourcePath: string
    resultPos: number
  }> = (() => {
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
      // Obtener metadata de cada PDF (nombre y número de páginas)
      const items: FileItem[] = []
      for (const p of files) {
        try {
          const info = await openPdf(p)
          const pc = info?.pageCount ?? 0
          items.push({
            path: p,
            name: info?.name ?? p.split('/').pop() ?? p,
            pageCount: pc,
            dataUrl: info?.dataUrl,
            thumbDataUrls: info?.thumbDataUrls ?? [],
            selected: Array.from({ length: pc }, () => true),
          })
        } catch (_) {
          items.push({ path: p, name: p.split('/').pop() ?? p, thumbDataUrls: [], selected: [] })
        }
      }
      setPaths((prev) => {
        const existing = new Map(prev.map((it) => [it.path, it]))
        for (const it of items) existing.set(it.path, it)
        const out = Array.from(existing.values())
        // initialize thumbPage for new items
        setThumbPage((tp) => {
          const copy = { ...tp }
          for (const it of out) {
            if (!(it.path in copy)) copy[it.path] = 0
          }
          return copy
        })
        return out
      })
    }
  }

  const handleClear = () => {
    setPaths([])
    setOutputPath(null)
    setMessage('Sin paginas seleccionadas')
  }

  const handleMerge = async () => {
    // Build pages map: include only files where selection differs from all-selected
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
    try {
      const result = await mergePdfs({ paths: paths.map((p) => p.path), pages, outputPath })
      if (!result) {
        toast.error('Error desconocido al combinar PDFs')
        return
      }
      setOutputPath(result.outputPath ?? null)
      setMessage(result.message)
      if (result.outputPath) {
        toast.success(result.message ?? 'PDF combinado creado')
      } else {
        toast.error(result.message ?? 'Error al crear PDF')
      }
    } catch (err: any) {
      toast.error('Error al combinar: ' + (err?.message ?? String(err)))
    } finally {
      setIsRunning(false)
    }
  }

  const handlePickDirectory = async () => {
    const dir = await pickDirectory('Selecciona carpeta de destino')
    if (dir) {
      setOutputPath(dir)
      const name = (dir || '').split(/\\|\//).pop() || dir
      toast.success(`Carpeta seleccionada: ${name}`)
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
    <div className="grid min-h-[calc(100vh-120px)] grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-[1fr_320px]">
      <Toaster position="top-right" />
      <section className="rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-sm font-semibold text-[#0f1824]">PDFs a combinar</h2>
          <div className="flex gap-3">
            <button type="button" onClick={handleClear} className="text-xs font-semibold text-[#e24c4b]">
              Limpiar todo
            </button>
            <button
              type="button"
              onClick={handleAdd}
              className="rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]"
            >
              Agregar PDF
            </button>
          </div>
        </div>
        <div className="mt-6 space-y-3 text-xs text-[#5a6b7f]">
          {paths.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[#d5dce6] bg-[#f7f9fc] py-20 text-center text-xs text-[#8a96a8]">
              <div className="grid h-10 w-10 place-items-center rounded-lg border border-[#d5dce6] bg-white text-[#5a6b7f]">
                ⬆
              </div>
              Agrega PDFs con el boton "Agregar PDF"
            </div>
          )}
          {paths.map((item) => (
            <div key={item.path} className="rounded-lg border border-[#d8dee8] bg-white px-3 py-2">
              <div className="flex items-start gap-3">
                <div className="flex-1 text-xs text-[#334155]">
                  <div className="font-semibold">{item.name}</div>
                  <div className="mt-2 flex items-center gap-2">
                    <div className="flex gap-2 text-[11px] text-[#3a4c64]">
                      <button
                        type="button"
                        onClick={() => {
                          setPaths((prev) =>
                            prev.map((p) =>
                              p.path === item.path ? { ...p, selected: Array.from({ length: p.pageCount ?? 0 }, () => true) } : p,
                            ),
                          )
                        }}
                        className="px-2 py-1 rounded bg-white border"
                      >
                        Todas
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setPaths((prev) =>
                            prev.map((p) =>
                              p.path === item.path ? { ...p, selected: Array.from({ length: p.pageCount ?? 0 }, () => false) } : p,
                            ),
                          )
                        }}
                        className="px-2 py-1 rounded bg-white border"
                      >
                        Ninguna
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setPaths((prev) => prev.map((p) => (p.path === item.path ? { ...p, selected: (p.selected ?? []).map((v) => !v) } : p)))
                        }}
                        className="px-2 py-1 rounded bg-white border"
                      >
                        Invertir
                      </button>
                    </div>
                    <span className="text-[11px] text-[#64748b]">
                      {(item.selected ?? []).filter(Boolean).length}/{item.pageCount ?? 0} págs.
                    </span>
                  </div>
                </div>
                <div className="flex flex-col items-center gap-1">
                  <button type="button" onClick={() => { setPaths(prev => { const idx = prev.findIndex(p => p.path === item.path); if (idx <= 0) return prev; const copy = prev.slice(); [copy[idx-1], copy[idx]] = [copy[idx], copy[idx-1]]; return copy }) }} className="text-xs text-[#6b7280] px-2">↑</button>
                  <button type="button" onClick={() => { setPaths(prev => { const idx = prev.findIndex(p => p.path === item.path); if (idx < 0 || idx === prev.length - 1) return prev; const copy = prev.slice(); [copy[idx+1], copy[idx]] = [copy[idx], copy[idx+1]]; return copy }) }} className="text-xs text-[#6b7280] px-2">↓</button>
                  <button type="button" onClick={() => { setPaths(prev => prev.filter(p => p.path !== item.path)) }} className="text-xs text-[#e11d48] px-2">🗑️</button>
                </div>
              </div>

              <div className="mt-2">
                {/* Thumbnails grid with pagination */}
                {/* Thumbnails: load successive chunks vertically (Load more) */}
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
                        <div key={`row-${p}`} className="flex gap-2">
                          {Array.from({ length: end - start }).map((_, i) => {
                            const idx = start + i
                            const selected = item.selected ? item.selected[idx] : false
                            const thumb = item.thumbDataUrls?.[idx] ?? ''
                            return (
                              <button
                                key={idx}
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
                                className={`relative h-16 w-[90px] flex-shrink-0 overflow-hidden rounded border ${selected ? 'border-[#10b981] bg-[#e6f4ea]' : 'border-[#e2e8f0] bg-white'}`}
                                title={`Página ${idx + 1}`}
                              >
                                {thumb ? (
                                  <img src={thumb} alt={`${item.name} p${idx + 1}`} className="mx-auto h-full w-auto object-contain" />
                                ) : (
                                  <div className="flex h-full w-full items-center justify-center text-[10px] text-[#7b8793]">P{idx + 1}</div>
                                )}
                                <span className="absolute bottom-0 left-0 right-0 bg-black/40 text-[10px] font-semibold text-white">{idx + 1}</span>
                              </button>
                            )
                          })}
                        </div>
                      )
                      rows.push(row)
                    }
                    return rows
                  })()}

                  {/* Load more / Show less buttons */}
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
                            className="px-3 py-1 rounded border bg-white text-[11px]"
                          >
                            Mostrar menos
                          </button>
                        )}
                        {cur < pages && (
                          <button
                            type="button"
                            onClick={() => setThumbPage((tp) => ({ ...tp, [item.path]: (tp[item.path] ?? 0) + 1 }))}
                            className="px-3 py-1 rounded border bg-white text-[11px]"
                          >
                            Cargar más
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
      </section>

      <aside className="flex flex-col gap-4 rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <h3 className="text-sm font-semibold text-[#0f1824]">Vista previa del resultado</h3>
        <div className="h-[420px] overflow-auto rounded-xl border border-[#d8dee8] bg-[#f7f9fc] p-2">
          {selectedPreviewItems.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-xs text-[#9aa6b2]">
              <div className="grid h-10 w-10 place-items-center rounded-lg border border-[#d5dce6] bg-white">◎</div>
              Sin páginas seleccionadas
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {selectedPreviewItems.map((it, idx) => (
                <button
                  key={it.key}
                  type="button"
                  className="relative overflow-hidden rounded border border-[#c7d2df] bg-white"
                  title={`${it.sourceName} — pág ${it.sourcePage} — pos ${it.resultPos}`}
                  onClick={() => {
                    setModalIndex(idx)
                    setModalOpen(true)
                  }}
                >
                  {it.thumb ? (
                    <img src={it.thumb} alt={`${it.sourceName} p${it.sourcePage}`} className="h-20 w-full object-cover" />
                  ) : (
                    <div className="flex h-20 w-full items-center justify-center text-[10px] text-[#7b8793]">P{it.sourcePage}</div>
                  )}
                  <div className="absolute bottom-0 left-0 right-0 bg-black/45 px-1 text-[10px] font-semibold text-white">{it.resultPos}</div>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="text-[11px] text-[#4b5563]">{selectedPreviewItems.length} página(s) seleccionada(s)</div>
        <div className="text-[11px] text-[#64748b]">{message}</div>
        <div className="mt-auto flex flex-col gap-3 text-xs text-[#5a6b7f]">
          <div className="flex items-center gap-2">
            <div className="flex-1 rounded-lg border border-[#d8dee8] bg-white px-3 py-2 truncate text-[11px]">
              {outputPath ? outputPath.split('/').pop() || outputPath : 'Selecciona carpeta'}
            </div>
            <button
              type="button"
              onClick={handlePickDirectory}
              className="flex-shrink-0 rounded-lg border border-[#cfd7e2] bg-white px-3 py-2 text-[11px] font-semibold text-[#3a4c64] hover:bg-[#f7f9fc]"
            >
              Seleccionar
            </button>
          </div>
          <button
            type="button"
            onClick={handleMerge}
            disabled={isRunning}
            className={`rounded-full px-4 py-2 text-xs font-semibold text-white ${isRunning ? 'bg-[#94b3d7] cursor-not-allowed' : 'bg-[#365b89]'}`}
          >
            {isRunning ? 'Combinando...' : 'Combinar y guardar'}
          </button>
          <button
            type="button"
            onClick={handleOpenResult}
            className="rounded-full border border-[#cfd7e2] px-4 py-2 text-xs font-semibold text-[#3a4c64]"
          >
            Abrir resultado
          </button>
        </div>
      </aside>
      {modalOpen && selectedPreviewItems.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 w-[720px] max-w-[95%] overflow-hidden rounded-2xl bg-white p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-[#0f1824]">Vista previa de páginas seleccionadas</div>
              <button
                onClick={() => setModalOpen(false)}
                className="rounded bg-[#f2f4f7] px-3 py-1 text-xs"
              >
                Cerrar
              </button>
            </div>
            <div className="mt-3 flex items-center justify-between gap-3">
              <button
                type="button"
                className="rounded border border-[#d1d9e6] px-2 py-1 text-xs"
                onClick={() => setModalIndex((prev) => Math.max(0, prev - 1))}
                disabled={modalIndex <= 0}
              >
                ◀
              </button>
              <div className="flex-1 rounded border border-[#e2e8f0] bg-[#f8fafc] p-3">
                {(() => {
                  const cur = selectedPreviewItems[modalIndex]
                  const src = cur ? modalThumbs[cur.key] ?? cur.thumb : ''
                  if (src) {
                    return (
                      <img src={src} alt={`${cur.sourceName} p${cur.sourcePage}`} className="mx-auto h-[420px] max-w-full object-contain" />
                    )
                  }
                  return <div className="grid h-[420px] place-items-center text-sm text-[#7b8793]">Sin miniatura</div>
                })()}
              </div>
              <button
                type="button"
                className="rounded border border-[#d1d9e6] px-2 py-1 text-xs"
                onClick={() => setModalIndex((prev) => Math.min(selectedPreviewItems.length - 1, prev + 1))}
                disabled={modalIndex >= selectedPreviewItems.length - 1}
              >
                ▶
              </button>
            </div>
            <div className="mt-3 text-xs text-[#334155]">
              <div><strong>PDF origen:</strong> {selectedPreviewItems[modalIndex]?.sourceName}</div>
              <div><strong>Página origen:</strong> {selectedPreviewItems[modalIndex]?.sourcePage}</div>
              <div><strong>Posición en resultado:</strong> {selectedPreviewItems[modalIndex]?.resultPos} de {selectedPreviewItems.length}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
