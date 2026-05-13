import { NavLink } from 'react-router-dom'

const tabs = [
  { label: 'Inicio', to: '/', icon: '⌂' },
  { label: 'Extraer', to: '/extract', icon: '▣' },
  { label: 'Merge', to: '/merge', icon: '⋈' },
  { label: 'OCR', to: '/ocr', icon: '◎' },
]

export function TabBar() {
  
  const handleCloseTab = (e: React.MouseEvent, label: string) => {
    e.preventDefault()
    e.stopPropagation()
    console.log(`Cerrando pestaña: ${label}`)
  }

  return (
    // Contenedor principal: gris claro (como la barra de título de la ventana) y borde inferior
    <section className="flex items-end bg-[#e2e8f0] pt-2 px-2 border-b border-slate-300 shadow-sm relative z-10">
      
      {/* Sección Izquierda: Logo y Título (centrados verticalmente con padding inferior para alinear) */}
      <div className="flex shrink-0 items-center gap-3 font-semibold w-48 lg:w-60 pb-2 px-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded bg-blue-600 text-[8px] font-bold uppercase tracking-widest text-white shadow-sm">
          PDF
        </span>
        <div className="min-w-0">
          <p className="truncate text-[12px] font-bold text-slate-800">Gestor Documental</p>
        </div>
      </div>

      {/* Sección Central: Pestañas */}
      <div className="flex flex-1 items-end gap-1 overflow-x-auto custom-scrollbar">
        {tabs.map((tab) => (
          <NavLink
            key={tab.label}
            to={tab.to}
            className={({ isActive }) =>
              `group flex h-9 min-w-[120px] max-w-[220px] flex-1 shrink-0 items-center justify-between rounded-t-lg border border-b-0 px-3 text-[12px] font-semibold transition-colors ${
                isActive
                  // TRUCO DE NAVEGADOR: relative top-[1px] la empuja 1px abajo para tapar la línea del padre
                  ? 'relative top-[1px] z-10 bg-white border-slate-300 text-blue-700' 
                  // Pestaña inactiva: sin bordes visibles, fondo transparente que se oscurece al hover
                  : 'bg-transparent border-transparent text-slate-500 hover:bg-slate-300/50 hover:text-slate-700'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`text-[14px] shrink-0 ${isActive ? 'text-blue-600' : 'text-slate-400'}`}>
                    {tab.icon}
                  </span>
                  <span className="truncate">{tab.label}</span>
                  
                </div>
                {/* Botón de Cerrar (X) estilo navegador (se hace redondo al hover) */}
                <button
                  type="button"
                  onClick={(e) => handleCloseTab(e, tab.label)}
                  title={`Cerrar ${tab.label}`}
                  className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] transition-all ${
                    isActive
                      ? 'opacity-100 text-slate-400 hover:bg-slate-200 hover:text-slate-800'
                      : 'opacity-0 text-slate-400 group-hover:opacity-100 hover:bg-slate-300 hover:text-slate-800'
                  }`}
                >
                  ✕
                </button>
                
              </>
            )}
          </NavLink>
        ))}
        <div className="pb-1">
           <button className="inline-flex h-7 w-7 items-center justify-center rounded transition hover:bg-slate-300/50 text-slate-500 hover:text-slate-800">
          +
        </button>
        </div>
       
      </div>

      {/* Sección Derecha: Menú de opciones (Alineado con el fondo) */}
      <div className="pb-1 pl-2">
        
        <button className="inline-flex h-7 w-7 items-center justify-center rounded transition hover:bg-slate-300/50 text-slate-500 hover:text-slate-800 ml-1">
          ⋮
        </button>
      </div>
    </section>
  )
}