import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

function ProtectedRoute({ children }) {
  const [authSession, setAuthSession] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    fetch('/api/v1/pool/auth/session', {
      credentials: 'include'
    })
      .then(res => res.json())
      .then(data => {
        setAuthSession(data)
        setLoading(false)
        
        if (!data.logged_in) {
          console.log('未登录，跳转到首页')
          navigate('/', { replace: true })
        }
      })
      .catch(err => {
        console.error('Session check failed:', err)
        setLoading(false)
        navigate('/', { replace: true })
      })
  }, [navigate])

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        fontFamily: 'BoutiqueBitmap, monospace',
        fontSize: '16px'
      }}>
        验证登录状态...
      </div>
    )
  }

  if (!authSession?.logged_in) {
    return null
  }

  return children
}

export default ProtectedRoute
