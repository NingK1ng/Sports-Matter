import { Outlet, NavLink } from 'react-router-dom'
import { useEffect, useState } from 'react'
import './Layout.css'
import CursorOverlay from './CheckIn/CursorOverlay'
import MembershipModal from './AuthModals/MembershipModal'

function Layout() {
  const [authSession, setAuthSession] = useState(null)
  const [cursorId, setCursorId] = useState(null)
  const [showMembershipModal, setShowMembershipModal] = useState(false)
  useEffect(() => {
    let active = true
    fetch('/api/v1/pool/auth/session', { credentials: 'include', cache: 'no-store' })
      .then(res => res.ok ? res.json() : Promise.reject(new Error('会话暂时不可用')))
      .then(data => { if (active) setAuthSession(data) })
      .catch(() => {})
    fetch('/api/v1/checkin/status', { credentials: 'include' })
      .then(res => res.ok ? res.json() : null)
      .then(data => { if (active) setCursorId(data?.selected_cursor_id ?? null) })
      .catch(() => {})
    return () => { active = false }
  }, [])
  return (
    <div className="layout">
      <CursorOverlay cursorId={cursorId} />
      <header className="header">
        <div className="layout-header-content">
          <nav className="nav">
            <NavLink to="/" className="nav-logo" aria-label="返回首页">
              <div className="logo-container">
                <img
                  src="/icons/home.svg"
                  alt="HOME"
                  className="logo-home"
                  draggable="false"
                />
                <div className="logo-bird" aria-hidden="true" />
                <h1 className="logo-text">Sports Matter</h1>
              </div>
            </NavLink>
            <NavLink 
              to="/literature" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              文献上新
            </NavLink>
            <NavLink 
              to="/journals" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              顶刊动向
            </NavLink>
            <NavLink 
              to="/sports-data" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              Sports Data
            </NavLink>
            <NavLink 
              to="/research-gap" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              What's it Worth?
            </NavLink>
            <NavLink 
              to="/knowledge-graph" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              热点图谱
            </NavLink>
            <NavLink 
              to="/sports-journals" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              运动科学期刊
            </NavLink>
            <NavLink 
              to="/literature-pool" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              Sports Pigeon
            </NavLink>
            <NavLink
              to="/ai-assistant"
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              Sports Agent
            </NavLink>
            <NavLink
              to="/arxiv-stream"
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              预印本前沿
            </NavLink>
          </nav>
          <div className="layout-auth">
            <button type="button" className="pixel-badge member-badge" onClick={() => setShowMembershipModal(true)}>
              会员
            </button>
          </div>
        </div>
      </header>
      <main className="main-content">
        <Outlet context={{ authSession }} />
      </main>
      {showMembershipModal && (
        <MembershipModal onClose={() => setShowMembershipModal(false)} authSession={authSession} />
      )}
    </div>
  )
}
export default Layout
