import { Routes, Route, Navigate } from 'react-router-dom'
import { TabBar } from './components/TabBar'
import { ExtractPage } from './pages/ExtractPage'
import { HomePage } from './pages/HomePage'
import { MergePage } from './pages/MergePage'
import { OcrPage } from './pages/OcrPage'

export default function App() {
  return (
    // 1. Cambiamos min-h-screen por h-screen, y usamos flex-col con overflow-hidden
    // Esto asegura que la "ventana" de tu app NUNCA genere un scrollbar externo.
    <div className="flex h-screen w-full flex-col overflow-hidden bg-[radial-gradient(circle_at_top_left,_#f6f7fb_0%,_#eef2f7_45%,_#e9eef5_100%)] text-[#0f1824]">
      
      {/* 2. Añadimos el TopBar que tenías importado */}

      
      {/* 3. El TabBar (shrink-0 asegura que las barras no se aplasten) */}
      <div className="shrink-0">
        <TabBar />
      </div>

      {/* 4. Contenedor Main: flex-1 y min-h-0 son LA CLAVE de oro. 
          Esto permite que cada Página (como OcrPage) tome el espacio sobrante
          y maneje su propio scroll interno sin empujar el diseño hacia abajo. */}
      <main className="relative flex flex-1 min-h-0">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/extract" element={<ExtractPage />} />
          <Route path="/merge" element={<MergePage />} />
          <Route path="/ocr" element={<OcrPage />} />
          
          {/* 5. Ruta de seguridad: Si la ruta no existe, lo regresa al inicio */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
