
export function ExtractPage() {
  return (
    <div className="flex min-h-[calc(100vh-120px)] flex-col gap-6 px-6 py-6 lg:flex-row">
      <section className="w-full max-w-sm rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <h2 className="text-sm font-semibold text-[#0f1824]">Referencia</h2>
        <button className="mt-4 rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]">
          Abrir PDF referencia
        </button>
        <div className="mt-4 space-y-2 text-xs text-[#5a6b7f]">
          <p>Referencia: sin archivo</p>
          <p>Tipo: -</p>
        </div>
        <input
          className="mt-4 w-full rounded-lg border border-[#d8dee8] bg-[#f7f9fc] px-3 py-2 text-xs"
          placeholder="Paginas de referencia (ej: 1,3-5)"
        />

        <div className="mt-6">
          <h3 className="text-xs font-semibold text-[#0f1824]">Patron de busqueda</h3>
          <textarea
            className="mt-3 h-28 w-full rounded-lg border border-[#d8dee8] bg-[#f7f9fc] px-3 py-2 text-xs"
            placeholder="Palabras clave / titulos / nombres de formato"
          />
        </div>

        <div className="mt-6">
          <h3 className="text-xs font-semibold text-[#0f1824]">Opciones avanzadas</h3>
          <input
            className="mt-3 w-full rounded-lg border border-[#d8dee8] bg-[#f7f9fc] px-3 py-2 text-xs"
            placeholder="Pagina sugerida en cada objetivo (ej: 1,2)"
          />
        </div>
      </section>

      <section className="flex-1 rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-sm font-semibold text-[#0f1824]">Objetivos y extraccion</h2>
          <div className="flex flex-wrap gap-3">
            <button className="rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]">
              Cargar PDFs objetivo
            </button>
            <button className="rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]">
              Carpeta destino
            </button>
          </div>
        </div>
        <div className="mt-4 space-y-2 text-xs text-[#5a6b7f]">
          <p>Archivos objetivo: 0</p>
          <p>Destino: C:\Users\CFE\AppData\Roaming\Flet\extraer-pdfs\storage\temp</p>
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <button className="flex items-center gap-2 rounded-full bg-[#365b89] px-5 py-2 text-xs font-semibold text-white shadow-sm">
            Buscar y extraer
          </button>
          <button className="rounded-full border border-[#cfd7e2] px-5 py-2 text-xs font-semibold text-[#9aa6b2]">
            Abrir vista previa
          </button>
        </div>
        <div className="mt-6 text-xs text-[#5a6b7f]">Sin busqueda ejecutada</div>
        <div className="mt-5">
          <h3 className="text-xs font-semibold text-[#0f1824]">Registro de operacion</h3>
          <div className="mt-2 h-60 rounded-xl border border-[#d8dee8] bg-white" />
        </div>
      </section>
    </div>
  )
}
