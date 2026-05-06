import { useState } from 'react'
import { mergePdfs, pickFiles } from '../services/api'
import { useAppState } from '../state/AppContext'
import { openPdf } from '../services/api'

export function MergePage() {
  const [paths, setPaths] = useState<string[]>([])
  const [outputPath, setOutputPath] = useState<string | null>(null)
  const [message, setMessage] = useState('Sin paginas seleccionadas')
  const { setCurrentPdf } = useAppState()

  const handleAdd = async () => {
    const files = await pickFiles({ multiple: true, title: 'Seleccionar PDFs para combinar' })
    if (files.length) {
      setPaths((prev) => Array.from(new Set([...prev, ...files])))
    }
  }

  const handleClear = () => {
    setPaths([])
    setOutputPath(null)
    setMessage('Sin paginas seleccionadas')
  }

  const handleMerge = async () => {
    const result = await mergePdfs({ paths, outputPath })
    if (!result) {
      return
    }
    setOutputPath(result.outputPath ?? null)
    setMessage(result.message)
  }

  const handleOpenResult = async () => {
    if (!outputPath) {
      return
    }
    const result = await openPdf(outputPath)
    if (result) {
      setCurrentPdf(result)
    }
  }

  return (
    <div className="grid min-h-[calc(100vh-120px)] grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-[1fr_320px]">
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
          {paths.map((path) => (
            <div key={path} className="rounded-lg border border-[#d8dee8] bg-white px-3 py-2">
              {path}
            </div>
          ))}
        </div>
      </section>

      <aside className="flex flex-col gap-4 rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <h3 className="text-sm font-semibold text-[#0f1824]">Vista previa del resultado</h3>
        <div className="flex h-36 flex-col items-center justify-center gap-2 rounded-xl border border-[#d8dee8] bg-[#f7f9fc] text-xs text-[#9aa6b2]">
          <div className="grid h-10 w-10 place-items-center rounded-lg border border-[#d5dce6] bg-white">◎</div>
          {message}
        </div>
        <div className="mt-auto flex flex-col gap-3 text-xs text-[#5a6b7f]">
          <div className="rounded-lg border border-[#d8dee8] bg-white px-3 py-2">
            {outputPath ?? 'Selecciona ruta de salida'}
          </div>
          <button
            type="button"
            onClick={handleMerge}
            className="rounded-full bg-[#365b89] px-4 py-2 text-xs font-semibold text-white"
          >
            Combinar y guardar
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
    </div>
  )
}
