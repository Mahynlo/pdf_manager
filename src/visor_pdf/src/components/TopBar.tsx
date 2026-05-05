import { NavLink } from 'react-router-dom'

export function TopBar() {
  return (
    <header className="flex flex-col gap-4 bg-[#1e2a38] px-6 py-4 text-white lg:flex-row lg:items-center lg:justify-between">
      <div className="flex items-center gap-3 font-semibold">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-[#ef5350] text-[10px] font-bold uppercase tracking-[0.2em]">
          pdf
        </span>
        <div>
          <p className="text-sm font-semibold">Extraer PDFs</p>
          <p className="text-[11px] text-[#c5d1df]">Centro de gestion documental</p>
        </div>
      </div>
      <nav className="flex flex-wrap items-center gap-3 text-[13px] font-semibold text-[#e7eef7]">
        <NavLink
          to="/"
          className="flex items-center gap-2 rounded-md px-2 py-1 transition hover:text-white"
        >
          <span className="h-2 w-2 rounded-full bg-white/90" /> Abrir PDF
        </NavLink>
        <NavLink
          to="/extract"
          className="flex items-center gap-2 rounded-md px-2 py-1 transition hover:text-white"
        >
          <span className="h-2 w-2 rounded-full bg-white/90" /> Extraer texto
        </NavLink>
        <NavLink
          to="/merge"
          className="flex items-center gap-2 rounded-md px-2 py-1 transition hover:text-white"
        >
          <span className="h-2 w-2 rounded-full bg-white/90" /> Combinar PDFs
        </NavLink>
        <div className="h-4 w-px bg-[#4a5c71]" />
        <NavLink
          to="/ocr"
          className="flex items-center gap-2 rounded-md px-2 py-1 transition hover:text-white"
        >
          <span className="h-2 w-2 rounded-full bg-white/90" /> OCR
        </NavLink>
      </nav>
    </header>
  )
}
