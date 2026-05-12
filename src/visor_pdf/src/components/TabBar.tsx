import { NavLink } from 'react-router-dom'

const tabs = [
  { label: 'Inicio', to: '/', icon: '⌂' },
  { label: 'Extraer PDF', to: '/extract', icon: '▣' },
  { label: 'Combinar PDFs', to: '/merge', icon: '⋈' },
  { label: 'OCR', to: '/ocr', icon: '◎' },
]

export function TabBar() {
  return (
    <section className="flex items-center gap-3 border-b border-[#d5dce6] bg-[#eef2f7] px-5 py-2">
      <div className="flex items-center gap-3 font-semibold ">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-[#ef5350] text-gray-100 text-[10px] font-bold uppercase tracking-[0.2em]">
          pdf
        </span>
        <div>
          <p className="text-sm font-semibold">Extraer PDFs</p>
          <p className="text-[11px] text-gray-500">Centro de gestion documental</p>
        </div>
      </div>
      
      <div className="flex flex-wrap items-center gap-2 px-12">
        {tabs.map((tab) => (
          <NavLink
            key={tab.label}
            to={tab.to}
            className={({ isActive }) =>
              `flex items-center gap-2 rounded-md border px-4 py-1 text-[13px] font-medium ${
                isActive
                  ? 'border-[#d5dce6] border-b-2 border-b-[#2c73d2] bg-white text-[#2d3c4f]'
                  : 'border-transparent text-[#5a6b7f]'
              }`
            }
          >
            <span className="text-sm">{tab.icon}</span>
            {tab.label}
          </NavLink>
        ))}
      </div>
      <button className="ml-auto text-base text-[#5a6b7f]">⋮</button>
    </section>
  )
}