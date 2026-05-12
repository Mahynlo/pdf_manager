interface RecentFile {
  name: string
  path: string
}

interface SidebarProps {
  files: RecentFile[]
  onSelect?: (path: string) => void
}

export function Sidebar({ files, onSelect }: SidebarProps) {
  return (
    // min-h-0 es clave aquí por si esta sidebar se pone dentro de un contenedor flex
    <aside className="flex h-full min-h-0 flex-col gap-4 border-r border-[#e3e8ef] bg-[#f7f9fc] px-5 py-6">
      
      <div className="shrink-0 flex items-center gap-2 text-sm font-semibold text-[#2d3c4f]">
        <span className="grid h-6 w-6 place-items-center rounded-full border border-[#cfd7e2] text-xs text-[#4c5b6d]">
          ↻
        </span>
        Archivos recientes
      </div>

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto pr-2 custom-scrollbar">
        {files.length === 0 ? (
          // Estado vacío
          <div className="mt-4 text-center text-xs text-[#5a6b7f]">
            No hay archivos recientes.
          </div>
        ) : (
          // Lista de archivos
          files.map((file) => (
            <button
              type="button"
              key={file.path} // Usamos path como key porque es único, el nombre podría repetirse
              onClick={() => onSelect?.(file.path)}
              className="group grid w-full grid-cols-[32px_1fr_auto] items-center gap-3 rounded-lg px-2 py-2 text-left transition hover:bg-[#edf1f7]"
            >
              <div className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-[#e43e3d] text-[10px] font-bold text-white shadow-sm">
                PDF
              </div>
              
              {/* min-w-0 es OBLIGATORIO en grid/flex para que el truncate funcione */}
              <div className="min-w-0">
                <p 
                  className="truncate text-[12px] font-semibold text-[#2d3c4f]" 
                  title={file.name} // Muestra el nombre completo al hacer hover
                >
                  {file.name}
                </p>
                <p 
                  className="truncate text-[10px] text-[#5a6b7f]" 
                  title={file.path}
                >
                  {file.path}
                </p>
              </div>

              <span className="shrink-0 text-sm text-[#a0abb8] transition-colors group-hover:text-[#2d3c4f]">
                ↗
              </span>
            </button>
          ))
        )}
      </div>
    </aside>
  )
}
