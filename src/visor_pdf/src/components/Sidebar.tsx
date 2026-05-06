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
    <aside className="flex h-full flex-col gap-4 border-r border-[#e3e8ef] bg-[#f7f9fc] px-5 py-6">
      <div className="flex items-center gap-2 text-sm font-semibold text-[#2d3c4f]">
        <span className="grid h-6 w-6 place-items-center rounded-full border border-[#cfd7e2] text-xs text-[#4c5b6d]">
          ↻
        </span>
        Archivos recientes
      </div>
      <div className="flex flex-1 flex-col gap-3 overflow-auto pr-2">
        {files.map((file) => (
          <button
            type="button"
            key={file.name}
            onClick={() => onSelect?.(file.path)}
            className="grid w-full grid-cols-[32px_1fr_auto] items-center gap-3 rounded-lg px-2 py-1 text-left transition hover:bg-[#edf1f7]"
          >
            <div className="grid h-7 w-7 place-items-center rounded-md bg-[#e43e3d] text-[10px] font-bold text-white">
              PDF
            </div>
            <div>
              <p className="text-[12px] font-semibold text-[#2d3c4f]">{file.name}</p>
              <p className="text-[10px] text-[#5a6b7f]">{file.path}</p>
            </div>
            <button className="text-sm text-[#5a6b7f]">↗</button>
          </button>
        ))}
      </div>
    </aside>
  )
}
