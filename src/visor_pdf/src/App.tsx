
import { Routes, Route } from 'react-router-dom'
import { TabBar } from './components/TabBar'
import { TopBar } from './components/TopBar'
import { ExtractPage } from './pages/ExtractPage'
import { HomePage } from './pages/HomePage'
import { MergePage } from './pages/MergePage'
import { OcrPage } from './pages/OcrPage'

export default function App() {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_#f6f7fb_0%,_#eef2f7_45%,_#e9eef5_100%)] text-[#0f1824]">
      <TopBar />
      <TabBar />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/extract" element={<ExtractPage />} />
        <Route path="/merge" element={<MergePage />} />
        <Route path="/ocr" element={<OcrPage />} />
      </Routes>
    </div>
  )
}
