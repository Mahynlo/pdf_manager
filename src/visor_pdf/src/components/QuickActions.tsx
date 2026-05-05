import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

export interface QuickAction {
    title: string
    description: string
    tone: 'info' | 'neutral' | 'accent'
    to: string
    icon: ReactNode
}

interface QuickActionsProps {
    actions: QuickAction[]
    onSelect?: (action: QuickAction) => void
}

const toneStyles: Record<QuickAction['tone'], string> = {
    info: 'bg-[#d9e7ff] text-[#2758c8]',
    neutral: 'bg-[#e4ebf4] text-[#3a4c64]',
    accent: 'bg-[#f0d8ff] text-[#7a2bd6]',
}

export function QuickActions({ actions }: QuickActionsProps) {
    return (
        <section className="flex flex-1 flex-col items-center gap-9 px-6 py-14 text-center">
            <div>
                <h1 className="text-[28px] font-bold text-[#0f1824]">¿Que quieres hacer?</h1>
                <p className="mt-2 text-sm text-[#5a6b7f]">Selecciona una opcion para comenzar</p>
            </div>

            <div className="grid w-full max-w-3xl grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
                {actions.map((action) => (
                    <NavLink to={action.to} key={action.title} className="no-underline">
                        <button
                            type="button"
                            key={action.title}
                            className="flex flex-col items-center gap-3 rounded-2xl border border-[#e2e7ef] bg-white px-6 py-6 text-left shadow-[0_16px_30px_rgba(15,24,36,0.16)] transition hover:-translate-y-1 hover:shadow-[0_20px_36px_rgba(15,24,36,0.18)]"
                        >
                            <div className={`grid h-14 w-14 place-items-center rounded-2xl ${toneStyles[action.tone]}`}>
                                <span className="h-7 w-7">{action.icon}</span>
                            </div>
                            <h4 className="text-sm font-bold text-[#2d3c4f]">{action.title}</h4>
                            <p className="text-xs text-[#5a6b7f]">{action.description}</p>
                        </button>
                    </NavLink>

                ))}
            </div>
        </section>
    )
}
