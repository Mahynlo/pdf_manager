export function MergePage() {
  return (
    <div className="grid min-h-[calc(100vh-120px)] grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-[1fr_320px]">
      <section className="rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-sm font-semibold text-[#0f1824]">PDFs a combinar</h2>
          <div className="flex gap-3">
            <button className="text-xs font-semibold text-[#e24c4b]">Limpiar todo</button>
            <button className="rounded-full border border-[#cfd7e2] bg-white px-4 py-2 text-xs font-semibold text-[#3a4c64]">
              Agregar PDF
            </button>
          </div>
        </div>
        <div className="mt-10 flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[#d5dce6] bg-[#f7f9fc] py-20 text-center text-xs text-[#8a96a8]">
          <div className="grid h-10 w-10 place-items-center rounded-lg border border-[#d5dce6] bg-white text-[#5a6b7f]">
            ⬆
          </div>
          Agrega PDFs con el boton "Agregar PDF"
        </div>
      </section>

      <aside className="flex flex-col gap-4 rounded-2xl border border-[#e3e8ef] bg-white/70 p-6 shadow-sm">
        <h3 className="text-sm font-semibold text-[#0f1824]">Vista previa del resultado</h3>
        <div className="flex h-36 flex-col items-center justify-center gap-2 rounded-xl border border-[#d8dee8] bg-[#f7f9fc] text-xs text-[#9aa6b2]">
          <div className="grid h-10 w-10 place-items-center rounded-lg border border-[#d5dce6] bg-white">◎</div>
          Sin paginas seleccionadas
        </div>
        <div className="mt-auto flex flex-col gap-3 text-xs text-[#5a6b7f]">
          <div className="rounded-lg border border-[#d8dee8] bg-white px-3 py-2">
            C:\Users\CFE\Documents\PDF_semantic_Editor\moto...
          </div>
          <button className="rounded-full bg-[#d5dce6] px-4 py-2 text-xs font-semibold text-[#8a96a8]">
            Combinar y guardar
          </button>
        </div>
      </aside>
    </div>
  )
}
