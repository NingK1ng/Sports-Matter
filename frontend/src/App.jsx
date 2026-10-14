import { useEffect, useState } from 'react'
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
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const initialize = () => {
    setFailed(false)
    fetch('/api/v1/pool/auth/session', { credentials: 'include', cache: 'no-store' })
      .then(res => { if (!res.ok) throw new Error('session'); return res.json() })
      .then(() => setReady(true)).catch(() => setFailed(true))
  }
  useEffect(initialize, [])
  if (!ready) return <div role="status" style={{ padding: 40, textAlign: 'center' }}>
    {failed ? <>暂时无法连接网站。<button onClick={initialize}>重新连接</button></> : '正在打开 Sports Matter…'}
  </div>
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
