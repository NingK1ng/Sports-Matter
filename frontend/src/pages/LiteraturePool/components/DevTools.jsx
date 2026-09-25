/**
 * Dev Tools - 开发者工具面板
 * 一键生成WiW卡片测试功能
 */
import { useState } from 'react'
import styles from '../LiteraturePool.module.css'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

function DevTools() {
  const [keywords, setKeywords] = useState('')
  const [track, setTrack] = useState('stream')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const getErrorMessage = (payload, fallback) => {
    const detail = payload?.detail ?? payload?.error ?? null
    if (typeof detail === 'string' && detail) return detail
    if (detail && typeof detail.message === 'string' && detail.message) return detail.message
    if (payload && typeof payload.message === 'string' && payload.message) return payload.message
    if (payload && typeof payload.msg === 'string' && payload.msg) return payload.msg
    return fallback
  }
  
  const handleQuickGenerate = async () => {
    if (!keywords.trim()) {
      setError('请输入关键词')
      return
    }
    
    setLoading(true)
    setError('')
    setResult(null)
    
    try {
      const response = await fetch(
        `${API_BASE}/pool/dev/quick_wiw?keywords=${encodeURIComponent(keywords)}&track=${track}`,
        { method: 'POST', credentials: 'include' }
      )
      
      const data = await response.json().catch(() => null)
      
      if (response.ok) {
        setResult(data)
      } else {
        throw new Error(getErrorMessage(data, '生成失败'))
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }
  
  return (
    <div className={styles.devTools}>
      <div className={styles.devToolsHeader}>
        <h3>🛠️ 开发者工具</h3>
        <p>快速测试WiW卡片生成功能</p>
      </div>
      
      <div className={styles.devToolsForm}>
        <div className={styles.formGroup}>
          <label>关键词</label>
          <input
            type="text"
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder="如: HIIT training"
            className={styles.input}
          />
        </div>
        
        <div className={styles.formGroup}>
          <label>数据源</label>
          <select value={track} onChange={(e) => setTrack(e.target.value)} className={styles.select}>
            <option value="stream">模块1 - 文献流</option>
            <option value="journals">模块2 - 顶刊追踪</option>
          </select>
        </div>
        
        <button
          onClick={handleQuickGenerate}
          disabled={loading}
          className={styles.devGenerateBtn}
        >
          {loading ? '生成中...' : '一键生成WiW'}
        </button>
        
        {error && (
          <div className={styles.devError}>
            ❌ {error}
          </div>
        )}
      </div>
      
      {result && (
        <div className={styles.devResult}>
          <h4>生成成功</h4>
          
          <div className={styles.sourceInfo}>
            <p><strong>来源PMID:</strong> {result.source_pmid}</p>
            <p><strong>文章标题:</strong> {result.source_article.title}</p>
            <p><strong>期刊:</strong> {result.source_article.journal} ({result.source_article.year})</p>
          </div>
          
          <div className={styles.wiwCard}>
            <h5>研究聚焦</h5>
            <p>{result.wiw_card.focus}</p>
            
            <h5>下一步研究问题</h5>
            <ul>
              {result.wiw_card.next_questions?.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
            
            <h5>矛盾与冲突</h5>
            <p>{result.wiw_card.conflicts}</p>
            
            <h5>研究空白</h5>
            <p>{result.wiw_card.gaps}</p>
            
            {result.wiw_card.top_journal_recommendations && result.wiw_card.top_journal_recommendations.length > 0 && (
              <>
                <h5>顶刊推荐 ({result.wiw_card.top_journal_recommendations.length}篇)</h5>
                <ul className={styles.journalList}>
                  {result.wiw_card.top_journal_recommendations.map((j, i) => (
                    <li key={i}>
                      <strong>{j.journal}</strong> ({j.year}): {j.title}
                    </li>
                  ))}
                </ul>
              </>
            )}
            
            {result.wiw_card.references && result.wiw_card.references.length > 0 && (
              <>
                <h5>相似文献 ({result.wiw_card.references.length}篇)</h5>
                <ul className={styles.refList}>
                  {result.wiw_card.references.slice(0, 5).map((ref, i) => (
                    <li key={i}>
                      <a href={ref.url} target="_blank" rel="noopener noreferrer">
                        {ref.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default DevTools
