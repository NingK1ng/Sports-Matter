import { Outlet, NavLink } from 'react-router-dom'
import { useEffect, useState } from 'react'
import './Layout.css'
import LoginModal from './AuthModals/LoginModal'
import MembershipModal from './AuthModals/MembershipModal'
import CursorOverlay from './CheckIn/CursorOverlay'

function Layout() {
  const [authSession, setAuthSession] = useState(null)
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [showMemberModal, setShowMemberModal] = useState(false)
  const [oauthError, setOauthError] = useState(null) // { code, detail }
  const [cursorId, setCursorId] = useState(() => {
    try {
      const saved = localStorage.getItem('sm_selected_cursor_id')
      const id = saved ? Number(saved) : null
      return Number.isFinite(id) && id ? id : null
    } catch {
      return null
    }
  })

  useEffect(() => {
    // OAuth 回调错误提示（QQ/微信）
    try {
      const params = new URLSearchParams(window.location.search || '')
      const code = (params.get('error') || '').trim()
      const detail = (params.get('detail') || '').trim()
      if (code) {
        setOauthError({ code, detail })
      }
    } catch (_) {
      // ignore
    }

    fetch('/api/v1/pool/auth/session', { credentials: 'include' })
      .then(res => res.json())
      .then(data => setAuthSession(data))
      .catch(() => setAuthSession(null))
  }, [])

  const isGuest = Boolean(
    authSession?.logged_in &&
      authSession?.user &&
      (authSession.user.is_guest || authSession.user.nickname === '访客' || authSession.user.nickname === '游客')
  )

  const isMember = Boolean(authSession?.logged_in && authSession?.user && authSession.user.is_member)
  const membershipIcon = (() => {
    if (!isMember) return null
    const tier = authSession?.user?.membership_tier
    if (authSession?.user?.membership_is_lifetime || tier === 'lifetime') {
      return { src: '/lifetime-heart.gif', alt: '终身会员' }
    }
    if (tier === 'yearly') return { src: '/yearly-food.png', alt: '年度会员' }
    if (tier === 'monthly') return { src: '/monthly-food.png', alt: '月度会员' }
    return null
  })()

  const refreshSession = async () => {
    try {
      const res = await fetch('/api/v1/pool/auth/session', { credentials: 'include' })
      const data = await res.json()
      setAuthSession(data)
    } catch (_) {
      // ignore
    }
  }

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
    if (!authSession?.logged_in || isGuest) {
      persistCursorId(null)
      return
    }

    ;(async () => {
      try {
        const res = await fetch('/api/v1/checkin/status', { credentials: 'include' })
        if (!res.ok) return
        const data = await res.json()
        persistCursorId(data?.selected_cursor_id ?? null)
      } catch {
        // ignore
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authSession?.logged_in, isGuest])

  const handleNavGuard = (e, { needLogin = false, needMember = false } = {}) => {
    if (needMember && !isMember) {
      e.preventDefault()
      setShowMemberModal(true)
      return
    }
    if (needLogin && isGuest) {
      e.preventDefault()
      setShowLoginModal(true)
    }
  }

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
              onClick={(e) => handleNavGuard(e, { needLogin: true })}
            >
              热点图谱
            </NavLink>
            <NavLink 
              to="/sports-journals" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
              onClick={(e) => handleNavGuard(e, { needLogin: true })}
            >
              运动科学期刊
            </NavLink>
            <NavLink 
              to="/literature-pool" 
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
              onClick={(e) => handleNavGuard(e, { needMember: true })}
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
            {(!authSession || isGuest) ? (
              <button
                type="button"
                className="qq-login-entry"
                onClick={() => setShowLoginModal(true)}
                aria-label="QQ登录"
              >
                <img
                  src="/qq-login.png"
                  alt="QQ登录"
                  className="qq-login-img"
                  draggable="false"
                />
              </button>
            ) : (
              <div className="layout-user-badge">
                {membershipIcon && (
                  <img
                    src={membershipIcon.src}
                    alt={membershipIcon.alt}
                    className="layout-membership-icon"
                    draggable="false"
                  />
                )}
                {authSession.user?.avatar && (
                  <img
                    src={authSession.user.avatar}
                    alt="avatar"
                    className="layout-user-avatar"
                    draggable="false"
                  />
                )}
                <span>{authSession.user?.nickname || '已登录'}</span>
              </div>
            )}
          </div>
        </div>
      </header>
      {oauthError && (
        <div
          style={{
            width: '100%',
            background: '#fff3cd',
            color: '#664d03',
            borderBottom: '1px solid #ffecb5',
            padding: '10px 14px',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px'
          }}
        >
          <div style={{ lineHeight: 1.3 }}>
            <strong>登录失败：</strong>
            <span>{oauthError.code}</span>
            {oauthError.detail ? <span style={{ marginLeft: 8, opacity: 0.9 }}>{oauthError.detail}</span> : null}
          </div>
          <button
            type="button"
            className="pixel-button"
            onClick={() => setOauthError(null)}
            style={{ padding: '4px 10px' }}
          >
            关闭
          </button>
        </div>
      )}
      <main className="main-content">
        <Outlet
          context={{
            authSession,
            openLogin: () => setShowLoginModal(true),
            openMembership: () => setShowMemberModal(true)
          }}
        />
      </main>

      {showLoginModal && <LoginModal onClose={() => setShowLoginModal(false)} />}
      {showMemberModal && (
        <MembershipModal
          onClose={() => setShowMemberModal(false)}
          authSession={authSession}
          onLoginRequired={() => {
            setShowMemberModal(false)
            setShowLoginModal(true)
          }}
          onMembershipUpdated={refreshSession}
        />
      )}
    </div>
  )
}

export default Layout
