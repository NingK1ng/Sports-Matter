import { useState, useRef, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import useLocalStorage from '../../hooks/useLocalStorage'
import TypewriterSubtitle from '../../components/TypewriterSubtitle'
import styles from './Assistant.module.css'

function Assistant() {
  const outlet = useOutletContext()
  const authSession = outlet?.authSession
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [citations, setCitations] = useState([])
  const [error, setError] = useState(null)
  const [reasoning, setReasoning] = useState([])
  const [streamTokenType, setStreamTokenType] = useState('token')
  const [statusText, setStatusText] = useState('')
  const eventSourceRef = useRef(null)
  const [messages, setMessages] = useState([])
  const assistantIndexRef = useRef(-1)
  const [sessionId, setSessionId] = useLocalStorage('assistant_session_id', null)
  const [sessionHistory, setSessionHistory] = useLocalStorage('assistant_session_history', [])
  const messagesWrapRef = useRef(null)
  const messagesEndRef = useRef(null)
  const [titleVisible, setTitleVisible] = useState(false)
  const [localSource, setLocalSource] = useState('both')  // 本地检索数据源: stream|journals|both
  
  // 设置
  const [useAgent, setUseAgent] = useState(false)
  const [topK, setTopK] = useState(10)
  const [model, setModel] = useState('deepseek-v4-flash')  // 模型选择
  const [reasoningChain, setReasoningChain] = useState('')  // 推理链

  const isMember = Boolean(authSession?.user?.is_member)
  const assistantQuota = authSession?.quota?.features?.assistant_chat
  const quotaHint = isMember
    ? '会员不限次数'
    : assistantQuota
        ? `本周剩余：${assistantQuota.remaining}/${assistantQuota.limit}`
        : '未登录/非会员每周免费 3 次'
  
  const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
  
  useEffect(() => {
    const timer = setTimeout(() => setTitleVisible(true), 300)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!sessionId) {
      setSessionId(`sid_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`)
    }
  }, [sessionId, setSessionId])

  useEffect(() => {
    // 对话新增时滚动到底部
    try {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    } catch {}
  }, [messages, loading])
  
  // 自动保存当前会话（消息变更时）
  useEffect(() => {
    if (messages.length > 0 && sessionId && !loading) {
      const firstUserMsg = messages.find(m => m.role === 'user')?.content || '新会话'
      const sessionTitle = firstUserMsg.slice(0, 50) + (firstUserMsg.length > 50 ? '...' : '')
      const existingIdx = sessionHistory.findIndex(s => s.id === sessionId)
      
      const sessionData = {
        id: sessionId,
        title: sessionTitle,
        timestamp: Date.now(),
        messages: messages,
        citations: citations
      }
      
      if (existingIdx >= 0) {
        const updated = [...sessionHistory]
        updated[existingIdx] = sessionData
        setSessionHistory(updated)
      } else {
        setSessionHistory([sessionData, ...sessionHistory])
      }
    }
  }, [messages, sessionId, loading])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    
    setLoading(true)
    setError(null)
    // 不再清空引用列表，保持同一会话内累积引用
    setReasoning([])
    setReasoningChain('')  // 清空推理链
    setStreamTokenType('token')
    setStatusText('')
    const userText = query.trim()
    setMessages(prev => {
      const next = prev.slice()
      next.push({ role: 'user', content: userText })
      assistantIndexRef.current = next.length
      next.push({ role: 'assistant', content: '' })
      return next
    })

    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    
    try {
      // 使用SSE流式接口
     const qs = new URLSearchParams({
        query: userText,
        use_agent: useAgent,
        top_k: topK,
        lang: 'zh',
        model: model,
        local_source: useAgent ? '' : localSource,
        session_id: sessionId || '',
        _ts: Date.now().toString(), // 防缓存
      })
      const eventSource = new EventSource(`${API_BASE}/assistant/chat-stream?` + qs.toString())
      eventSourceRef.current = eventSource
      
      // onopen: 连接建立
      eventSource.onopen = () => {
        setStatusText('已连接，开始生成…')
      }
      
      const handleMessage = (event) => {
        const data = JSON.parse(event.data)
        
        switch (data.type) {
          case 'meta':
            if (typeof data.stream_token_type === 'string') {
              setStreamTokenType(data.stream_token_type)
            }
            break
          case 'token':
            if (typeof data.text === 'string') {
              setMessages(prev => {
                const next = prev.slice()
                const i = assistantIndexRef.current
                if (i >= 0 && i < next.length) {
                  const cur = next[i]
                  next[i] = { ...cur, content: (cur.content || '') + data.text }
                }
                return next
              })
            }
            break
          case 'chain': {
            const { index, text, total } = data
            if (typeof text === 'string') {
              setReasoning(prev => {
                const next = [...prev]
                const idx = typeof index === 'number' && index > 0 ? index - 1 : next.length
                next[idx] = text
                return next
              })
            }
            if (typeof total === 'number' && typeof index === 'number') {
              setStatusText(`DeepSeek 深度思考中 (${index}/${total})`)
            } else {
              setStatusText('DeepSeek 深度思考中')
            }
            break
          }
          case 'citations':
            // 累积同一会话内的引用文献，按PMID去重
            if (Array.isArray(data.items)) {
              setCitations(prev => {
                const byKey = new Map()
                for (const c of prev) {
                  const key = c.pmid || `${c.idx}-${c.title}`
                  byKey.set(key, c)
                }
                for (const c of data.items) {
                  if (!c) continue
                  const key = c.pmid || `${c.idx}-${c.title}`
                  if (!byKey.has(key)) {
                    byKey.set(key, c)
                  }
                }
                return Array.from(byKey.values())
              })
            }
            break
          case 'reasoning':
            // 旧格式：steps数组
            if (Array.isArray(data.steps)) {
              setReasoning(data.steps)
            }
            // 新格式：reasoner模型的推理链
            if (typeof data.content === 'string') {
              setReasoningChain(data.content)
              setStatusText('推理过程已生成')
            }
            break
          case 'status':
            setStatusText(data.text || '')
            break
          case 'correction':
            setMessages(prev => {
              const next = prev.slice()
              const i = assistantIndexRef.current
              if (i >= 0 && i < next.length) {
                next[i] = { ...next[i], content: data.text || '' }
              }
              return next
            })
            break
          case 'error':
            setError(data.message)
            setStatusText('生成失败')
            eventSource.close()
            eventSourceRef.current = null
            setLoading(false)
            break
          case 'done':
            eventSource.close()
            eventSourceRef.current = null
            setLoading(false)
            break
        }
      }

      // 默认 message 事件（后端未设置 event: 时）
      eventSource.onmessage = handleMessage
      // 命名事件（后端使用 event: xxx 时）
      ;['meta','token','chain','citations','reasoning','status','correction','error','done']
        .forEach(evt => eventSource.addEventListener(evt, handleMessage))
      
      eventSource.onerror = (err) => {
        console.error('SSE error:', err)
        setError('连接中断，请重试')
        setStatusText('连接中断')
        eventSource.close()
        eventSourceRef.current = null
        setLoading(false)
      }
      
    } catch (err) {
      setError(err.message || '请求失败')
      setStatusText('请求失败')
      setLoading(false)
    }
  }
  
  const scrollToCitation = (idx) => {
    const element = document.getElementById(`citation-${idx}`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      element.classList.add(styles.highlight)
      setTimeout(() => element.classList.remove(styles.highlight), 3000)
    }
  }

  const handleNewSession = () => {
    // 保存当前会话到历史记录
    if (messages.length > 0 && sessionId) {
      const firstUserMsg = messages.find(m => m.role === 'user')?.content || '新会话'
      const sessionTitle = firstUserMsg.slice(0, 50) + (firstUserMsg.length > 50 ? '...' : '')
      const existingIdx = sessionHistory.findIndex(s => s.id === sessionId)
      
      const sessionData = {
        id: sessionId,
        title: sessionTitle,
        timestamp: Date.now(),
        messages: messages,
        citations: citations
      }
      
      if (existingIdx >= 0) {
        // 更新现有会话
        const updated = [...sessionHistory]
        updated[existingIdx] = sessionData
        setSessionHistory(updated)
      } else {
        // 添加新会话到历史记录
        setSessionHistory([sessionData, ...sessionHistory])
      }
    }
    
    // 创建新会话
    setSessionId(`sid_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`)
    setMessages([])
    setCitations([])
    setReasoning([])
    setReasoningChain('')
    setStatusText('')
    setQuery('')
  }
  
  const loadSession = (session) => {
    // 保存当前会话
    if (messages.length > 0 && sessionId && sessionId !== session.id) {
      const firstUserMsg = messages.find(m => m.role === 'user')?.content || '新会话'
      const sessionTitle = firstUserMsg.slice(0, 50) + (firstUserMsg.length > 50 ? '...' : '')
      const existingIdx = sessionHistory.findIndex(s => s.id === sessionId)
      
      const sessionData = {
        id: sessionId,
        title: sessionTitle,
        timestamp: Date.now(),
        messages: messages,
        citations: citations
      }
      
      if (existingIdx >= 0) {
        const updated = [...sessionHistory]
        updated[existingIdx] = sessionData
        setSessionHistory(updated)
      } else {
        setSessionHistory([sessionData, ...sessionHistory])
      }
    }
    
    // 加载选中的会话
    setSessionId(session.id)
    setMessages(session.messages || [])
    setCitations(session.citations || [])
    setReasoning([])
    setReasoningChain('')
    setStatusText('')
    setQuery('')
  }
  
  const formatTimestamp = (timestamp) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diff = now - date
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(diff / 3600000)
    const days = Math.floor(diff / 86400000)
    
    if (minutes < 1) return '刚刚'
    if (minutes < 60) return `${minutes}分钟前`
    if (hours < 24) return `${hours}小时前`
    if (days < 7) return `${days}天前`
    return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  }
  
  return (
    <div className={styles.assistantPage}>
      <header className={styles.pageHeader}>
        <div className={styles.pageHeaderInner}>
          <span className={styles.agentBird} aria-hidden="true" />
          <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>Sports Agent</h1>
        </div>
        <TypewriterSubtitle
          text={[
            '尽管问，鸽子为您叼回真实文献答疑解惑！',
            '可能它需要饲料才会工作奥！',
          ]}
          active={titleVisible}
        />
      </header>
      
      <div className={styles.container}>
        {/* 左侧设置面板 */}
        <aside className={styles.sidebar}>
        <h3>设置</h3>
        
        <div className={styles.setting}>
          <button onClick={handleNewSession} disabled={loading} className={styles.newSessionBtn}>
            新建会话
          </button>
        </div>

        <div className={styles.setting}>
          <label style={{ fontWeight: 600 }}>检索模式</label>
          <div>
            <label>
              <input
                type="radio"
                name="search-mode"
                checked={!useAgent}
                onChange={() => setUseAgent(false)}
              />
              本地模式（默认）
            </label>
            <div>
              <small>使用文献流与顶刊追踪数据进行检索</small>
            </div>
          </div>
          <div style={{ marginTop: 6 }}>
            <label>
              <input
                type="radio"
                name="search-mode"
                checked={useAgent}
                onChange={() => setUseAgent(true)}
              />
              在线模式（PubMed 全库）
            </label>
            <div>
              <small>连接 PubMed 在线检索</small>
            </div>
          </div>
        </div>

        {!useAgent && (
          <div className={styles.setting}>
            <label style={{ fontWeight: 600 }}>本地数据源</label>
            <div>
              <label>
                <input
                  type="radio"
                  name="local-source"
                  value="stream"
                  checked={localSource === 'stream'}
                  onChange={() => setLocalSource('stream')}
                />
                文献上新
              </label>
            </div>
            <div>
              <label>
                <input
                  type="radio"
                  name="local-source"
                  value="journals"
                  checked={localSource === 'journals'}
                  onChange={() => setLocalSource('journals')}
                />
                顶刊追踪
              </label>
            </div>
            <div>
              <label>
                <input
                  type="radio"
                  name="local-source"
                  value="both"
                  checked={localSource === 'both'}
                  onChange={() => setLocalSource('both')}
                />
                文献上新及顶刊追踪
              </label>
            </div>
          </div>
        )}

        <div className={styles.setting}>
          <label>召回数量: {topK}</label>
          <input
            type="range"
            min="5"
            max="20"
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
          />
        </div>
        
        {/* 会话历史 */}
        <div className={styles.sessionHistory}>
          <h3>会话历史</h3>
          {sessionHistory.length > 0 ? (
            <div className={styles.sessionList}>
              {sessionHistory.map((session) => (
                <div
                  key={session.id}
                  className={`${styles.sessionItem} ${session.id === sessionId ? styles.active : ''}`}
                  onClick={() => loadSession(session)}
                >
                  <div className={styles.sessionTitle}>{session.title}</div>
                  <div className={styles.sessionTime}>{formatTimestamp(session.timestamp)}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.sessionEmpty}>暂无历史会话</div>
          )}
        </div>
      </aside>

      {/* 中间对话区 */}
      <main className={styles.main}>
        <div className={styles.chat}>
          {/* 消息区 */}
          <div className={styles.messages} ref={messagesWrapRef}>
            {messages.map((m, idx) => (
              <div key={idx} className={`${styles.messageRow} ${m.role === 'user' ? styles.right : styles.left}`}>
                {m.role === 'assistant' && (
                  <div className={styles.avatarBox}>
                    <span className={styles.assistantAvatar} />
                  </div>
                )}
                <div className={`${styles.bubble} ${m.role === 'user' ? styles.bubbleUser : styles.bubbleAssistant}`}>
                  <div
                    dangerouslySetInnerHTML={{
                      __html:
                        m.role === 'assistant'
                          ? (m.content || '')
                              .replace(/\[(\d+(?:,\s*\d+)*)\]/g, (match, ids) => {
                                const idList = ids.split(',').map(id => id.trim())
                                return idList
                                  .map(
                                    id =>
                                      `<span class="${styles.citation}" onclick="scrollToCitation(${id})">[${id}]</span>`
                                  )
                                  .join(', ')
                              })
                              .replace(/\n/g, '<br />')
                          : (m.content || '').replace(/\n/g, '<br />'),
                    }}
                  />
                </div>
              </div>
            ))}
            {loading && (
              <div className={`${styles.messageRow} ${styles.left}`}>
                <div className={`${styles.bubble} ${styles.bubbleAssistant}`}>
                  <span className={styles.typing}><span></span><span></span><span></span></span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* 输入栏固定在底部 */}
          <form onSubmit={handleSubmit} className={styles.inputBar}>
            <textarea
              className={styles.inputBox}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="输入您的问题（如：High-intensity interval training对心血管健康的影响）"
              rows={1}
              disabled={loading}
            />
            <button type="submit" className={styles.sendButton} disabled={loading || !query.trim()}>
              {loading ? '生成中...' : '发送'}
            </button>
          </form>

          {error && (
            <div className={styles.error}>
              ❌ {error}
            </div>
          )}

          {/* 状态提示已隐藏 */}
          {/* {statusText && (
            <div className={styles.status}>
              <span>{statusText}</span>
              {loading && streamTokenType && (
                <span className={styles.streamType}> · 流式：{streamTokenType}</span>
              )}
            </div>
          )} */}
        </div>

        {/* 推理信息 */}
        {reasoning.length > 0 && (
          <div className={styles.reasoning}>
            <h4>DeepSeek 深度思维</h4>
            <ol className={styles.reasoningList}>
              {reasoning.map((step, idx) => (
                <li key={idx} className={styles.reasoningItem}>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        )}
        
        {reasoningChain && (
          <div className={styles.reasoningChain}>
            <h4>🧠 推理过程 (Reasoner)</h4>
            <div className={styles.reasoningContent}>
              {reasoningChain}
            </div>
          </div>
        )}
      </main>

      {/* 右侧引用列表 */}
      <aside className={styles.citations}>
        <h3>引用文献 ({citations.length})</h3>
        {citations.length > 0 && (
          <div className={styles.citationList}>
            {citations.map((cite) => (
              <div 
                key={cite.idx} 
                id={`citation-${cite.idx}`}
                className={styles.citationItem}
              >
                <span className={styles.citationIdx}>[{cite.idx}]</span>
                <div>
                  <p className={styles.citationTitle}>
                    <a href={cite.url} target="_blank" rel="noopener noreferrer">
                      {cite.title}
                    </a>
                  </p>
                  <small className={styles.citationMeta}>
                    PMID: {cite.pmid} | {cite.journal_name || 'N/A'} | {cite.publication_year || 'N/A'}
                  </small>
                </div>
              </div>
            ))}
          </div>
        )}
      </aside>
      </div>

      <footer className={styles.quotaFooter}>
        {quotaHint}
      </footer>
    </div>
  )
}

// 全局函数（用于dangerouslySetInnerHTML中的onclick）
window.scrollToCitation = (idx) => {
  const element = document.getElementById(`citation-${idx}`)
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.classList.add('highlight')
    setTimeout(() => element.classList.remove('highlight'), 3000)
  }
}

export default Assistant
