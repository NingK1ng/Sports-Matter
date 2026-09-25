import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import LiteratureStream from './pages/LiteratureStream/index'
import JournalsTracking from './pages/JournalsTracking'
import ResearchGap from './pages/ResearchGap'
import LiteraturePool from './pages/LiteraturePool'
import Assistant from './pages/Assistant'
import KnowledgeGraph from './pages/KnowledgeGraph'
import SportsJournals from './pages/SportsJournals'
import ArxivStream from './pages/ArxivStream'
import ComingSoon from './pages/ComingSoon'
import SportsData from './pages/SportsData'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route element={<Layout />}>
        {/* 公开模块 - 模块1、2 */}
        <Route path="literature" element={<LiteratureStream />} />
        <Route path="journals" element={<JournalsTracking />} />
        <Route path="sports-data" element={<SportsData />} />

        {/* 全部模块均可匿名访问 */}
        <Route path="research-gap" element={<ResearchGap />} />
        <Route path="knowledge-graph" element={<KnowledgeGraph />} />
        <Route path="sports-journals" element={<SportsJournals />} />
        <Route path="literature-pool" element={<LiteraturePool />} />
        <Route path="ai-assistant" element={<Assistant />} />
        <Route path="arxiv-stream" element={<ArxivStream />} />
      </Route>
    </Routes>
  )
}

export default App
