/**
 * Login Page - 开发模式登录（QQ登录配置后启用）
 */
import { useState } from 'react'
import styles from '../LiteraturePool.module.css'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

function LoginPage({ onLoginSuccess }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  
  const handleDevLogin = async () => {
    setLoading(true)
    setError('')
    
    try {
      const response = await fetch(`${API_BASE}/pool/auth/dev/login`, { method: 'POST' })
      const data = await response.json()
      
      if (response.ok) {
        onLoginSuccess(data.access_token, {
          user_id: data.user_id,
          nickname: data.nickname,
          avatar: data.avatar
        })
      } else {
        throw new Error(data.detail || '登录失败')
      }
    } catch (err) {
      setError(err.message)
      setLoading(false)
    }
  }
  
  return (
    <div className={styles.loginContainer}>
      <div className={styles.loginCard}>
        <h2>文献池登录</h2>
        <p className={styles.loginHint}>开发模式：点击下方按钮登录</p>
        
        {error && (
          <div className={styles.errorMessage}>
            <span className={styles.errorIcon}>⚠️</span>
            <p>{error}</p>
          </div>
        )}
        
        <button 
          onClick={handleDevLogin} 
          className={styles.devLoginBtn}
          disabled={loading}
        >
          {loading ? '登录中...' : '一键登录'}
        </button>
        
        <p className={styles.loginTips}>
          注：QQ登录需配置QQ互联信息后启用
        </p>
      </div>
    </div>
  )
}

export default LoginPage
