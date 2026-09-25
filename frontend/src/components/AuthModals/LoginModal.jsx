import { useState, useEffect } from 'react'
import './AuthModals.css'

function LoginModal({ onClose }) {
  const [qrUrl, setQrUrl] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    document.body.style.overflow = 'hidden'

    // 获取二维码URL
    fetch('/api/v1/pool/auth/qq/login')
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          throw new Error(data.detail || 'QQ登录未配置')
        }
        return data
      })
      .then((data) => {
        setQrUrl(data.qr_url)
        setLoading(false)
      })
      .catch((err) => {
        console.error('Failed to load QR code:', err)
        setError(err?.message || 'QQ登录需要在QQ互联创建并审核“网站应用”')
        setLoading(false)
      })

    return () => {
      document.body.style.overflow = 'unset'
    }
  }, [])

  const handleQQLogin = () => {
    if (!qrUrl) return
    window.location.href = qrUrl
  }

  const handleDevLogin = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/v1/pool/dev/login', {
        method: 'POST',
        credentials: 'include'
      })
      if (res.ok) {
        window.location.reload()
      } else {
        setError('开发登录失败')
      }
    } catch (err) {
      console.error('Dev login failed:', err)
      setError('开发登录失败')
    }
    setLoading(false)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="auth-modal pixel-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <h2 className="modal-title">登录</h2>

        <div className="qq-login-modal">
          <button
            type="button"
            className="qq-login-entry"
            onClick={handleQQLogin}
            disabled={!qrUrl || loading || Boolean(error)}
            aria-label="QQ登录"
          >
            <img
              src="/qq-login.png"
              alt="QQ登录"
              className="qq-login-img"
              draggable="false"
            />
          </button>
          {!error && <p className="qr-hint">点击按钮使用QQ登录</p>}
        </div>

        {loading && <div className="loading-text">加载中...</div>}

        {error && !loading && (
          <div className="error-container">
            <div className="error-text">{error}</div>
            <div className="dev-login-section">
              <p className="dev-hint">开发环境快捷登录：</p>
              <button className="pixel-button" onClick={handleDevLogin}>
                开发登录（测试用）
              </button>
              <p className="dev-note">
                正式QQ登录需要：<br/>
                1. QQ互联创建“网站应用”并审核通过<br/>
                2. 配置回调地址（QQ_REDIRECT_URI）<br/>
                3. 获得AppID（QQ_APP_ID）与AppKey（QQ_APP_KEY）
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default LoginModal
