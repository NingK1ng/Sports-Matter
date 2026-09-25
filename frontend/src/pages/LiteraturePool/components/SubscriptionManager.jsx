/**
 * Subscription Manager - 订阅管理组件
 */
import { useState, useEffect } from 'react'
import SubscriptionList from './SubscriptionList'
import styles from '../LiteraturePool.module.css'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

function SubscriptionManager({
  selectedSubscription,
  onSelectSubscription,
  onRequireLogin,
  onRequireMembership,
}) {
  const [subscriptions, setSubscriptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [formData, setFormData] = useState({ query_text: '' })
  const [error, setError] = useState('')
  
  useEffect(() => {
    fetchSubscriptions()
  }, [])

  const getErrorMessage = (payload, fallback) => {
    const detail = payload?.detail ?? payload?.error ?? null
    if (typeof detail === 'string' && detail) return detail
    if (detail && typeof detail.message === 'string' && detail.message) return detail.message
    if (payload && typeof payload.message === 'string' && payload.message) return payload.message
    if (payload && typeof payload.msg === 'string' && payload.msg) return payload.msg
    return fallback
  }

  const getErrorCode = (payload) => {
    const detail = payload?.detail
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
      return detail.code
    }
    return null
  }

  const maybeOpenGate = (status, code) => {
    if (status === 401 || code === 'LOGIN_REQUIRED') {
      onRequireLogin && onRequireLogin()
      return true
    }
    if (status === 403 || code === 'MEMBERSHIP_REQUIRED') {
      onRequireMembership && onRequireMembership()
      return true
    }
    return false
  }
  
  const fetchSubscriptions = async () => {
    try {
      const response = await fetch(`${API_BASE}/pool/subscriptions`, {
        credentials: 'include',
      })
      
      const data = await response.json().catch(() => null)
      
      if (response.ok) {
        const items = Array.isArray(data?.subscriptions) ? data.subscriptions : []
        setSubscriptions(items)
        
        // 自动选择第一个订阅
        if (items.length > 0 && !selectedSubscription) {
          onSelectSubscription(items[0])
        }
      } else {
        const code = getErrorCode(data)
        const message = getErrorMessage(data, '获取订阅列表失败')
        maybeOpenGate(response.status, code)
        throw new Error(message)
      }
    } catch (err) {
      // 只显示非网络错误
      if (err.message !== 'Failed to fetch') {
        setError(err.message)
      }
    } finally {
      setLoading(false)
    }
  }
  
  const handleCreateSubscription = async (e) => {
    e.preventDefault()
    setError('')
    
    if (!formData.query_text) {
      setError('查询文本不能为空')
      return
    }
    
    try {
      const response = await fetch(`${API_BASE}/pool/subscriptions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(formData)
      })
      
      const data = await response.json().catch(() => null)
      
      if (response.ok) {
        setSubscriptions([...subscriptions, data])
        setFormData({ query_text: '' })
        setShowCreateForm(false)
        onSelectSubscription(data)
      } else {
        const code = getErrorCode(data)
        const message = getErrorMessage(data, '创建订阅失败')
        maybeOpenGate(response.status, code)
        throw new Error(message)
      }
    } catch (err) {
      setError(err.message)
    }
  }
  
  const handleDeleteSubscription = async (id) => {
    if (!confirm('确定要删除此订阅吗？')) return
    
    try {
      const response = await fetch(`${API_BASE}/pool/subscriptions/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      
      if (response.ok) {
        setSubscriptions(subscriptions.filter(sub => sub.id !== id))
        
        if (selectedSubscription?.id === id) {
          onSelectSubscription(null)
        }
      } else {
        const data = await response.json().catch(() => null)
        const code = getErrorCode(data)
        const message = getErrorMessage(data, '删除订阅失败')
        maybeOpenGate(response.status, code)
        throw new Error(message)
      }
    } catch (err) {
      setError(err.message)
    }
  }
  
  const handleRefreshSubscription = async (id) => {
    if (!confirm('刷新订阅将清空现有卡片，新卡片将在24小时内生成。确定继续吗？')) return
    
    try {
      const response = await fetch(`${API_BASE}/pool/subscriptions/${id}/refresh`, {
        method: 'POST',
        credentials: 'include',
      })
      
      const data = await response.json().catch(() => null)
      
      if (response.ok) {
        alert(data.message)
        // 刷新当前Feed
        window.location.reload()
      } else {
        const code = getErrorCode(data)
        const message = getErrorMessage(data, '刷新订阅失败')
        maybeOpenGate(response.status, code)
        throw new Error(message)
      }
    } catch (err) {
      setError(err.message)
    }
  }
  
  if (loading) {
    return (
      <div className={styles.subscriptionManager}>
        {[1,2,3].map(i => (
          <div key={i} className={styles.cardSkeleton}>
            <div className={styles.skeletonBar} style={{width:'70%'}}></div>
            <div className={styles.skeletonBar} style={{width:'90%'}}></div>
            <div className={styles.skeletonBar} style={{width:'50%'}}></div>
          </div>
        ))}
      </div>
    )
  }
  
  return (
    <div className={styles.subscriptionManager}>
      <div className={styles.subscriptionHeader}>
        <h2>我的订阅</h2>
        {subscriptions.length < 3 && (
          <button
            onClick={() => setShowCreateForm(!showCreateForm)}
            className={styles.createBtn}
          >
            + 新建订阅
          </button>
        )}
      </div>
      
      {error && <div className={styles.errorMessage}>{error}</div>}
      
      {showCreateForm && (
        <form onSubmit={handleCreateSubscription} className={styles.createForm}>
          <textarea
            placeholder="查询关键词（如：sports injury prevention）"
            value={formData.query_text}
            onChange={(e) => setFormData({ ...formData, query_text: e.target.value })}
            className={styles.formTextarea}
          />
          <div className={styles.formActions}>
            <button type="submit" className={styles.submitBtn}>创建</button>
            <button
              type="button"
              onClick={() => setShowCreateForm(false)}
              className={styles.cancelBtn}
            >
              取消
            </button>
          </div>
        </form>
      )}
      
      <SubscriptionList
        subscriptions={subscriptions}
        selectedSubscription={selectedSubscription}
        onSelectSubscription={onSelectSubscription}
        onDeleteSubscription={handleDeleteSubscription}
        onRefreshSubscription={handleRefreshSubscription}
      />
    </div>
  )
}

export default SubscriptionManager
