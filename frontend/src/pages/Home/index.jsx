import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './index.css'
import CheckInModal from '../../components/CheckIn/CheckInModal'
import CursorOverlay from '../../components/CheckIn/CursorOverlay'
import MembershipModal from '../../components/AuthModals/MembershipModal'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const CHECK_IN_ENABLED = false

function Home() {
  const navigate = useNavigate()
  const [keywords, setKeywords] = useState([])
  const [titleVisible, setTitleVisible] = useState(false)
  const [subtitleVisible, setSubtitleVisible] = useState(false)
  const [visitorCount, setVisitorCount] = useState(0)
  const [showSiteIntro, setShowSiteIntro] = useState(false)
  const [authSession, setAuthSession] = useState(null)
  const [showCheckInModal, setShowCheckInModal] = useState(false)
  const [showMembershipModal, setShowMembershipModal] = useState(false)
  const [cursorId, setCursorId] = useState(() => {
    try {
      const saved = localStorage.getItem('sm_selected_cursor_id')
      const id = saved ? Number(saved) : null
      return Number.isFinite(id) && id ? id : null
    } catch {
      return null
    }
  })

  const siteIntroUrl = 'https://mp.weixin.qq.com/s?__biz=MzcxMDE0MjcwMQ==&mid=2247483669&idx=1&sn=f2e118fd6aea7810bfaa884081687b0d'

  useEffect(() => {
    // 标题淡入动画
    setTimeout(() => {
      setTitleVisible(true)
    }, 300)
    // 访问次数动画
    let count = 0
    const target = 5080
    const duration = 2000
    const increment = target / (duration / 50)
    const countInterval = setInterval(() => {
      count += increment
      if (count >= target) {
        setVisitorCount(target)
        clearInterval(countInterval)
      } else {
        setVisitorCount(Math.floor(count))
      }
    }, 50)
    
    return () => {
      clearInterval(countInterval)
    }
  }, [])

  // 主标题出现后，再延迟一段时间让副标题淡入
  useEffect(() => {
    if (!titleVisible) return
    const timer = setTimeout(() => {
      setSubtitleVisible(true)
    }, 800) // 主标题动画约1s，这里再多留一点间隔
    return () => clearTimeout(timer)
  }, [titleVisible])

  const refreshSession = async () => {
    try {
      const res = await fetch('/api/v1/pool/auth/session', { credentials: 'include' })
      const data = await res.json()
      setAuthSession(data)
    } catch (err) {
      console.error('Failed to fetch session:', err)
    }
  }

  // 检查登录状态
  useEffect(() => {
    refreshSession()
  }, [])

  const fetchKeywords = async () => {
    try {
      const response = await fetch(`${API_BASE}/graph/communities?source=literature&window=1d`, {
        credentials: 'include'
      })
      if (response.status === 401 || response.status === 403) {
        return
      }
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const data = await response.json()
      const items = Array.isArray(data?.items) ? data.items : []
      const seen = new Set()
      const out = []
      for (const comm of items) {
        const terms = Array.isArray(comm?.representative_terms) ? comm.representative_terms : []
        for (const t of terms) {
          const raw = typeof t === 'string' ? t : (t?.term || '')
          const term = (raw || '').toString().trim()
          if (!term) continue
          if (term.length < 3) continue
          const key = term.toLowerCase()
          if (seen.has(key)) continue
          if (/\b(community|communities|other|unclustered|misc|miscellaneous|general|unknown)\b/i.test(term)) continue
          seen.add(key)
          out.push(term)
          if (out.length >= 20) break
        }
        if (out.length >= 20) break
      }
      setKeywords(out)
    } catch (error) {
      console.error('Failed to fetch keywords:', error)
    }
  }
  
  useEffect(() => {
    if (authSession?.logged_in) {
      fetchKeywords()
    } else {
      setKeywords([])
    }
  }, [authSession])

  const modules = [
    {
      name: '文献上新',
      icon: '/icons/book.png',
      desc: '每日最新运动科学文献信息汇总分类',
      path: '/literature'
    },
    {
      name: '顶刊动向',
      icon: '/icons/eye.png',
      desc: '时刻监控运动科学顶刊及综合顶刊的上新文献',
      path: '/journals'
    },
    {
      name: "What's it Worth?",
      icon: '/icons/gold.png',
      desc: '关联指定文献，调用LLM汇总分析',
      path: '/research-gap'
    },
    {
      name: '热点图谱',
      icon: '/icons/graph.png',
      desc: '文献上新及顶刊动向板块近期热门关键词',
      path: '/knowledge-graph'
    },
    {
      name: '运动科学期刊',
      icon: '/icons/journal.png',
      desc: '全部运动科学相关期刊信息汇总！',
      path: '/sports-journals'
    },
    {
      name: 'Sports Pigeon',
      icon: '/icons/mail.png',
      desc: '飞鸽传信，叼回指定关键词的最新文献及关联网络',
      path: '/literature-pool'
    },
    {
      name: 'Sports Agent',
      icon: '/icons/pc.png',
      desc: '接入PubMed或网站本地库，回答一切问题',
      path: '/ai-assistant'
    },
    {
      name: '预印本前沿',
      icon: '/icons/arxiv.png',
      desc: '在海量未出版的预印本中探索运动科学最前沿',
      path: '/arxiv-stream'
    },
    {
      name: 'Sports Data',
      icon: '/icons/graph.png',
      desc: '欢迎尝试20年代最先进的搜索引擎',
      path: '/sports-data'
    }
  ]

  const persistCursorId = (nextId) => {
    const id = nextId ? Number(nextId) : null
    const safeId = Number.isFinite(id) && id ? id : null
    setCursorId(safeId)
    try {
      if (safeId) {
        localStorage.setItem('sm_selected_cursor_id', String(safeId))
      } else {
        localStorage.removeItem('sm_selected_cursor_id')
      }
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    if (authSession == null) return
    if (!authSession?.logged_in) {
      persistCursorId(null)
      return
    }

    ;(async () => {
      try {
        const res = await fetch('/api/v1/checkin/status', { credentials: 'include' })
        if (!res.ok) return
        const data = await res.json()
        if (data?.selected_cursor_id) {
          persistCursorId(data.selected_cursor_id)
        }
      } catch {
        // ignore
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authSession?.logged_in])

  const handleModuleNavigate = (path) => navigate(path)
  const openCheckin = () => setShowCheckInModal(true)

  return (
    <div className="home-page wood-texture">
      <CursorOverlay cursorId={cursorId} />
      {/* Header with title animation - Async Area style */}
      <header className="home-header">
        <div className="header-content">
          <div className="logo-section">
            <span
              className={`home-bird ${titleVisible ? 'home-bird-visible' : ''}`}
              aria-hidden="true"
            />
            <h1 className={`main-title ${titleVisible ? 'fade-in' : ''}`}>
              Sports Matter!
            </h1>
            <p className={`tagline ${subtitleVisible ? 'fade-in' : ''}`}>
              Sports matter, so does their research.
            </p>
          </div>

          <div className="auth-badges">
            <button type="button" className="pixel-badge member-badge" onClick={() => setShowMembershipModal(true)}>
              会员
            </button>
            {CHECK_IN_ENABLED && (
              <button type="button" className="pixel-badge checkin-badge" onClick={openCheckin}>
                签到
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main TV Screen - Module Cards */}
      <section className="tv-container">
        <div className="tv-screen pixel-card">
          <div className="module-grid">
            {modules.map((module, index) => {
              return (
                <div
                  key={index}
                  className="module-card"
                  onClick={() => handleModuleNavigate(module.path)}
                  style={{ cursor: 'pointer' }}
                >
                  {module.icon ? (
                    <img src={module.icon} alt={module.name} className="module-icon-img" />
                  ) : (
                    <div className="module-icon-text">{module.name[0]}</div>
                  )}
                  <h3 className="module-name">{module.name}</h3>
                  <p className="module-desc">{module.desc}</p>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* Trending Keywords Scrollbar */}
      {keywords.length > 0 && (
        <section className="keywords-scrollbar">
          <div className="keywords-track custom-scrollbar">
            <div className="keywords-inner">
              {keywords.concat(keywords).map((keyword, index) => (
                <span key={index} className="keyword-tag">{keyword}</span>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Site Intro Section */}
      <section className="site-intro-section">
        <h2 className="section-title" onClick={() => setShowSiteIntro(!showSiteIntro)} style={{ cursor: 'pointer' }}>
          {showSiteIntro ? '▼' : '▶'} 网站介绍
        </h2>
        {showSiteIntro && (
          <div className="site-intro-container">
            <a
              href={siteIntroUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="site-intro-card"
            >
              查看网站介绍文章
            </a>
          </div>
        )}
      </section>

      {showMembershipModal && (
        <MembershipModal onClose={() => setShowMembershipModal(false)} authSession={authSession} onMembershipUpdated={refreshSession} />
      )}
      {CHECK_IN_ENABLED && showCheckInModal && (
        <CheckInModal
          onClose={() => setShowCheckInModal(false)}
          onCursorChanged={(id) => persistCursorId(id)}
        />
      )}
    </div>
  )
}

export default Home
