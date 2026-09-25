/**
 * Feed View - Feed流展示组件
 */
import { useState, useEffect } from 'react'
import TrackSwitcher from './TrackSwitcher'
import WiWCard from './WiWCard'
import ArticleList from './ArticleList'
import styles from '../LiteraturePool.module.css'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

function FeedView({ subscription, onRequireLogin, onRequireMembership }) {
  const [feedData, setFeedData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedTrack, setSelectedTrack] = useState('all')  // all | stream | journals
  
  useEffect(() => {
    if (subscription) {
      fetchFeed()
    }
  }, [subscription])

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
  
  const fetchFeed = async () => {
    try {
      setLoading(true)
      const response = await fetch(
        `${API_BASE}/pool/feed/${subscription.id}`,
        {
          credentials: 'include',
        }
      )
      
      const data = await response.json().catch(() => null)
      
      if (response.ok) {
        setFeedData(data)
      } else {
        const code = getErrorCode(data)
        const message = getErrorMessage(data, '获取Feed失败')
        maybeOpenGate(response.status, code)
        throw new Error(message)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }
  
  const devGenerate = async (track) => {
    try {
      const res = await fetch(
        `${API_BASE}/pool/dev/generate_wiw?subscription_id=${subscription.id}&track=${track}`,
        {
          method: 'POST',
          credentials: 'include',
        }
      )
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        const code = getErrorCode(data)
        const message = getErrorMessage(data, '生成失败')
        maybeOpenGate(res.status, code)
        throw new Error(message)
      }
      await fetchFeed()
    } catch (e) {
      alert(e.message)
    }
  }
  
  if (loading) {
    return (
      <div className={styles.feedView}>
        <div className={styles.cardsGrid}>
          {[1,2,3].map(i => (
            <div key={i} className={styles.cardSkeleton}>
              <div className={styles.skeletonBar} style={{width:'60%'}}></div>
              <div className={styles.skeletonBar} style={{width:'90%'}}></div>
              <div className={styles.skeletonBar} style={{width:'80%'}}></div>
            </div>
          ))}
        </div>
      </div>
    )
  }
  
  if (error) {
    return (
      <div className={styles.feedView}>
        <div className={styles.errorMessage}>{error}</div>
        <button onClick={fetchFeed} className={styles.retryButton}>重试</button>
      </div>
    )
  }
  
  if (!feedData) {
    return <div className={styles.feedView}>暂无数据</div>
  }
  
  const { stream_cards, journals_cards, journals_articles } = feedData
  
  // 根据选择的轨道过滤卡片
  const displayStreamCards = (selectedTrack === 'all' || selectedTrack === 'stream') ? stream_cards : []
  const displayJournalsCards = (selectedTrack === 'all' || selectedTrack === 'journals') ? journals_cards : []
  
  return (
    <div className={styles.feedView}>
      <div className={styles.feedHeader}>
        <h2>{subscription.title}</h2>
        <TrackSwitcher
          selectedTrack={selectedTrack}
          onSelectTrack={setSelectedTrack}
        />
      </div>
      {(window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button className={styles.trackBtn} onClick={() => devGenerate('stream')}>开发：生成文献流卡片</button>
          <button className={styles.trackBtn} onClick={() => devGenerate('journals')}>开发：生成顶刊卡片</button>
        </div>
      )}
      
      {/* 模块1轨道卡片 */}
      {displayStreamCards.length > 0 && (
        <section className={styles.trackSection}>
          <h3>文献流卡片 ({stream_cards.length})</h3>
          <div className={styles.cardsGrid}>
            {displayStreamCards.map(card => (
              <WiWCard key={card.id} card={card} />
            ))}
          </div>
        </section>
      )}
      
      {/* 模块2轨道卡片 */}
      {displayJournalsCards.length > 0 && (
        <section className={styles.trackSection}>
          <h3>顶刊卡片 ({journals_cards.length})</h3>
          <div className={styles.cardsGrid}>
            {displayJournalsCards.map(card => (
              <WiWCard key={card.id} card={card} />
            ))}
          </div>
        </section>
      )}
      
      {/* 模块2文献列表 */}
      {(selectedTrack === 'all' || selectedTrack === 'journals') && journals_articles.length > 0 && (
        <section className={styles.trackSection}>
          <h3>顶刊文献列表 ({journals_articles.length})</h3>
          <ArticleList articles={journals_articles} />
        </section>
      )}
      
      {/* 空状态 */}
      {displayStreamCards.length === 0 && displayJournalsCards.length === 0 && (
        <div className={styles.emptyFeed}>
          <p>暂无卡片</p>
          <p>新卡片将在24小时内生成</p>
        </div>
      )}
    </div>
  )
}

export default FeedView
