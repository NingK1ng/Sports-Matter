/**
 * 知识图谱 - 社区气泡图可视化
 * 基于Cytoscape.js实现，展示研究社区（不是论文节点）
 */
import { useState, useEffect, useRef } from 'react'
import { useOutletContext } from 'react-router-dom'
import * as echarts from 'echarts'
import TypewriterSubtitle from '../../components/TypewriterSubtitle'
import styles from './KnowledgeGraph.module.css'
import { recommendedPixelStyle } from './BubbleVariants'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export default function KnowledgeGraph() {
  const outlet = useOutletContext()
  const authSession = outlet?.authSession
  const openLogin = outlet?.openLogin
  const openMembership = outlet?.openMembership
  const isGuest = Boolean(authSession?.user?.is_guest || authSession?.user?.nickname === '访客' || authSession?.user?.nickname === '游客')
  const isMember = Boolean(authSession?.user?.is_member)

  const [loading, setLoading] = useState(true)
  const [communities, setCommunities] = useState([])
  const [snapshot, setSnapshot] = useState(null)
  const [selectedSource, setSelectedSource] = useState('literature')
  const [selectedWindow, setSelectedWindow] = useState('30d')
  const [selectedCommunity, setSelectedCommunity] = useState(null)
  const [popover, setPopover] = useState(null) // { x, y, community }
  const [error, setError] = useState(null)
  const [filteredKeyword, setFilteredKeyword] = useState(null)
  const [globalKeywords, setGlobalKeywords] = useState([])
  // 按「数据源+时间窗口」缓存图谱与WiW结果，避免切换模块时丢失
  const [graphCache, setGraphCache] = useState({}) // key -> { communities, snapshot }
  const [wiwStateByKey, setWiwStateByKey] = useState({}) // key -> { [communityId]: {...} }
  const [expandedComms, setExpandedComms] = useState(new Set([0, 1, 2]))  // 默认展开前3个社区
  const [titleVisible, setTitleVisible] = useState(false)
	  const chartRef = useRef(null)
	  const chartInstance = useRef(null)
	  const containerRef = useRef(null)
	  const popoverRef = useRef(null)
	  const STOPWORDS = useRef(new Set(["a","an","the","and","or","of","to","in","on","for","with","without","by","from","as","at","is","are","was","were","be","been","being","this","that","these","those","it","its","their","his","her","we","you","they","our","my","your","not","no","yes","what","why","how","current","future","past","new","novel","more","less","many","various","several","impact","effect","effects","role","study","studies","research","analysis","methods","approach","approaches","factors","outcomes","population","participants","care","healthcare","professional","professionals","training","patient","patients","male","female","men","women","home","case","cases","group","groups","trial","trials","community","communities","other","unclustered","misc","miscellaneous","general","unknown"]))
	  const BANNED = useRef(new Set(["systematic review","meta-analysis","scoping review","narrative review","review","randomized controlled trial","randomised controlled trial","clinical trial","pilot study","case report","retrospective study","prospective study","cohort study","cross-sectional study","protocol"]))
	  const SYNONYMS = useRef({
    'acl': 'anterior cruciate ligament',
    'anterior cruciate ligament': 'acl',
    'vo2 max': 'vo2max',
    'vo2max': 'vo2 max',
    'hrv': 'heart rate variability',
    'heart rate variability': 'hrv',
    'emg': 'electromyography',
    'electromyography': 'emg',
    'pcl': 'posterior cruciate ligament',
    'posterior cruciate ligament': 'pcl'
  })

  // 当前视图对应的 key 与 WiW 状态
  const currentKey = `${selectedSource}:${selectedWindow}`
  const wiwState = wiwStateByKey[currentKey] || {}

	  const normalizeTermClient = (t) => {
	    const normalized = (t || '').toLowerCase().replace(/[_\-/]+/g, ' ').replace(/[^\w\s\+]+/g, '').replace(/\s+/g, ' ').trim()
	    return SYNONYMS.current[normalized] || normalized
	  }
	
	  const normalizeTextClient = (t) => {
	    return (t || '')
	      .toLowerCase()
	      .replace(/[_\-/]+/g, ' ')
	      .replace(/[^\w\s\+]+/g, ' ')
	      .replace(/\s+/g, ' ')
	      .trim()
	  }

  const isValidTermClient = (t) => {
    const s = normalizeTermClient(t)
    if (!s || s.length < 3) return false
    if (/^\d+$/.test(s)) return false
    for (const banned of BANNED.current) { if (s.includes(banned)) return false }
    const tokens = s.split(' ')
    const kept = tokens.filter(x => x && !STOPWORDS.current.has(x))
    return kept.length > 0
  }

  const getMainTerm = (terms) => {
    const arr = Array.isArray(terms) ? terms : []
    for (const t of arr) {
      const term = typeof t === 'string' ? t : (t?.term || '')
      if (isValidTermClient(term)) return normalizeTermClient(term)
    }
    return ''
  }

	  const termMatches = (term1, term2) => {
	    const t1 = normalizeTermClient(term1)
	    const t2 = normalizeTermClient(term2)
	    if (t1 === t2) return true
    // 检查是否互为同义词
    if (SYNONYMS.current[t1] === t2 || SYNONYMS.current[t2] === t1) return true
    // 检查包含关系（模糊匹配）
    if (t1.includes(t2) || t2.includes(t1)) return true
	    return false
	  }
	
	  const isGenericCommunityName = (t) => {
	    const s = (t || '').toString().toLowerCase().trim()
	    if (!s) return true
	    return /\b(community|communities|other|unclustered|misc|miscellaneous|general|unknown)\b/.test(s)
	  }
	
	  const getCommunityTitle = (comm) => {
	    const lbl = (comm?.llm_label || '').trim()
	    if (lbl && !isGenericCommunityName(lbl)) return lbl
	    const main = getMainTerm(comm?.representative_terms || [])
	    if (main && !isGenericCommunityName(main)) return main
	    const id = comm?.community_id ? String(comm.community_id) : ''
	    return id ? `社区 ${id}` : '社区'
	  }

	  const paperMatchesKeyword = (paper, keyword) => {
	    const kw = (keyword || '').trim()
	    if (!kw) return true

	    const paperKeywords = Array.isArray(paper?.keywords) ? paper.keywords : []
	    if (paperKeywords.length > 0) {
	      return paperKeywords.some((t) => termMatches(t, kw))
	    }

	    const title = normalizeTextClient(paper?.title || '')
	    const abstract = normalizeTextClient(paper?.abstract || '')
	    const kwRaw = normalizeTextClient(kw)
	    const kwSyn = SYNONYMS.current[kwRaw] || kwRaw
	    const candidates = new Set([kwRaw, kwSyn].filter(Boolean))
	    for (const c of candidates) {
	      if (c && (title.includes(c) || abstract.includes(c))) return true
	    }
	    return false
	  }
  
  // 根据关键词筛选文献
  const filterPapersByKeyword = (keyword) => {
    setFilteredKeyword(keyword)
  }
  
  // 获取筛选后的论文列表
  const getFilteredPapers = () => {
    if (!selectedCommunity || !filteredKeyword) {
      return selectedCommunity?.top_papers || []
    }
    
    // 筛选包含该关键词的论文
    const allPapers = selectedCommunity.top_papers || []
    return allPapers.filter((paper) => paperMatchesKeyword(paper, filteredKeyword))
  }

  // 汇总全局关键词（来自所有社区的代表性关键词与主标签），按权重降序
	  const aggregateKeywords = (comms) => {
	    const m = new Map()
	    const push = (term, w = 1) => {
	      const t = normalizeTermClient(term)
      if (!isValidTermClient(t)) return
      const prev = m.get(t) || { term: t, weight: 0, count: 0 }
      prev.weight += (typeof w === 'number' ? w : 1)
      prev.count += 1
      m.set(t, prev)
	    }
	    ;(comms || []).forEach((comm) => {
	      const terms = comm.representative_terms || []
	      for (const it of terms) {
	        const raw = typeof it === 'string' ? it : (it && typeof it.term === 'string' ? it.term : '')
	        if (!raw) continue
	
	        const papers = comm.top_papers || []
	        let hits = 0
	        for (const p of papers) {
	          if (paperMatchesKeyword(p, raw)) hits += 1
	          if (hits >= 2) break
	        }
	        if (hits < 2) continue
	
	        if (typeof it === 'string') push(raw, 1)
	        else if (it && typeof it.term === 'string') push(raw, it.score ?? 1)
	      }
	      // 主标签仅在至少 2 篇 top_papers 命中时进入“关键词面板”
	      // （避免出现“关键词下无文章 / 仅1篇”的体验）
	      const lbl = (comm.llm_label || '').trim()
      if (lbl) {
        const papers = comm.top_papers || []
        let hits = 0
        for (const p of papers) {
          if (paperMatchesKeyword(p, lbl)) hits += 1
          if (hits >= 2) break
        }
        if (hits >= 2) push(lbl, 1.2)
      }
    })
    const arr = Array.from(m.values())
    arr.sort((a, b) => (b.weight - a.weight) || (b.count - a.count) || a.term.localeCompare(b.term))
    return arr.slice(0, 50)
  }

  const getTopCommunities = (sourceList) => {
    const list = Array.isArray(sourceList || communities) ? [...(sourceList || communities)] : []
    if (!list.length) return []
    // 按规模降序，取前5个社区
    return list
      .slice()
      .sort((a, b) => (b.size || 0) - (a.size || 0))
      .slice(0, 5)
  }

  const loadWiwInternal = async (snapshotId, communityId, keyOverride) => {
    if (!snapshotId || !communityId) return
    const key = keyOverride || currentKey
    // 标记指定key下该社区WiW为loading
    setWiwStateByKey((prev) => {
      const prevForKey = prev[key] || {}
      return {
        ...prev,
        [key]: {
          ...prevForKey,
          [communityId]: { ...(prevForKey[communityId] || {}), loading: true, error: null }
        }
      }
    })
    try {
      const res = await fetch(
        `${API_BASE}/graph/snapshots/${encodeURIComponent(snapshotId)}/community/${encodeURIComponent(
          communityId
        )}/wiw`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ lang: 'zh' })
        }
      )
      if (!res.ok) {
        throw new Error(`WiW请求失败: HTTP ${res.status}`)
      }
      const data = await res.json()
      setWiwStateByKey((prev) => {
        const prevForKey = prev[key] || {}
        return {
          ...prev,
          [key]: {
            ...prevForKey,
            [communityId]: {
              loading: false,
              error: null,
              text: data?.wiw_analysis || '',
              generated_at: data?.generated_at || '',
              citations: data?.citations || []
            }
          }
        }
      })
    } catch (e) {
      setWiwStateByKey((prev) => {
        const key = keyOverride || currentKey
        const prevForKey = prev[key] || {}
        return {
          ...prev,
          [key]: {
            ...prevForKey,
            [communityId]: {
              ...(prevForKey[communityId] || {}),
              loading: false,
              error: e.message || 'WiW生成失败'
            }
          }
        }
      })
    }
  }

  const handleLoadWiw = async (communityId) => {
    if (!snapshot || !snapshot.snapshot_id || !communityId) return
    await loadWiwInternal(snapshot.snapshot_id, communityId, currentKey)
  }

  const renderWiwWithLinks = (wiw) => {
    if (!wiw || !wiw.text) return null
    const text = wiw.text
    const citations = wiw.citations || []
    const citationMap = new Map()
    citations.forEach((c) => {
      if (!c || typeof c.index !== 'number') return
      const key = String(c.index)
      citationMap.set(key, c.url || null)
    })

    const nodes = []
    const re = /\[文献(\d+)\]/g
    let lastIndex = 0
    let match
    while ((match = re.exec(text)) !== null) {
      const idx = match[1]
      const start = match.index
      if (start > lastIndex) {
        nodes.push(text.slice(lastIndex, start))
      }
      const url = citationMap.get(idx)
      const label = `[文献${idx}]`
      if (url) {
        nodes.push(
          <a
            key={`wiw-ref-${idx}-${start}`}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: '#a5b4fc', textDecoration: 'underline' }}
          >
            {label}
          </a>
        )
      } else {
        nodes.push(label)
      }
      lastIndex = re.lastIndex
    }
    if (lastIndex < text.length) {
      nodes.push(text.slice(lastIndex))
    }
    return nodes
  }

  // 从关键词打开对应社区的弹卡（选择包含该词且规模最大的社区）
  const openPopoverForKeyword = (kw) => {
    const s = normalizeTermClient(kw)
    let best = null
    for (const comm of communities || []) {
      let hit = false
      // 使用termMatches进行同义词匹配
      if (termMatches(comm.llm_label || '', s)) hit = true
      if (!hit) {
        for (const t of (comm.representative_terms || [])) {
          const tt = typeof t === 'string' ? t : (t?.term || '')
          if (termMatches(tt, s)) {
            hit = true
            break
          }
        }
      }
      // 候选术语匹配
      if (!hit && comm.llm_candidates) {
        for (const candidate of comm.llm_candidates) {
          if (termMatches(candidate, s)) {
            hit = true
            break
          }
        }
      }
      if (!hit) continue

      // 关键词门禁：至少命中 2 篇 top_papers（避免出现“0/1篇文章的关键词社区”）
      const papers = comm.top_papers || []
      let hits = 0
      for (const p of papers) {
        if (paperMatchesKeyword(p, s)) hits += 1
        if (hits >= 2) break
      }
      if (hits < 2) continue

      if (!best || (comm.size || 0) > (best.size || 0)) best = comm
    }
    if (!best) {
      console.log(`未找到包含关键词"${kw}"的社区`)
      return
    }
    setFilteredKeyword(s)
    const dom = containerRef.current
    const rect = dom ? dom.getBoundingClientRect() : { width: window.innerWidth, height: 800 }
    const x = Math.max(20, Math.min(rect.width - 20, rect.width * 0.65))
    const y = Math.max(20, Math.min(rect.height - 20, rect.height * 0.5))
    const place = 'left'
    setPopover({ x, y, place, community: best })
  }

  useEffect(() => {
    const timer = setTimeout(() => setTitleVisible(true), 300)
    return () => clearTimeout(timer)
  }, [])

  // 访问控制：访客禁止访问；非会员锁定为「文献上新」图谱
  useEffect(() => {
    if (!authSession) return
    if (isGuest) return
    if (!isMember && selectedSource !== 'literature') {
      setSelectedSource('literature')
    }
  }, [authSession, isGuest, isMember, selectedSource])

  useEffect(() => {
    if (!authSession) return
    if (isGuest) return
    loadGraph()
    
    // 响应式调整
    const handleResize = () => {
      if (chartInstance.current) {
        chartInstance.current.resize()
      }
    }
    window.addEventListener('resize', handleResize)
    
    return () => {
      window.removeEventListener('resize', handleResize)
      if (chartInstance.current) {
        chartInstance.current.dispose()
        chartInstance.current = null
      }
    }
  }, [authSession, isGuest, selectedSource, selectedWindow])

  const loadGraph = async (source = selectedSource, windowSize = selectedWindow, options = {}) => {
    const { force = false } = options
    const key = `${source}:${windowSize}`

    // 若已有缓存且非强制刷新，则直接使用缓存数据，避免切换模块时重置结果
    if (!force && graphCache[key] && Array.isArray(graphCache[key].communities)) {
      const cached = graphCache[key]
      const cachedItems = cached.communities || []
      setCommunities(cachedItems)
      setSnapshot(cached.snapshot || null)
      setGlobalKeywords(aggregateKeywords(cachedItems))
      setSelectedCommunity(null)
      setPopover(null)
      setError(null)
      setLoading(false)

      // 重要：切换时间窗时会 dispose 图表；缓存命中也需要重新渲染，否则会出现空白
      if (cachedItems && cachedItems.length > 0) {
        renderCommunityGraph(cachedItems)
      }
      return
    }

    setLoading(true)
    setError(null)
    setSelectedCommunity(null)
    
    try {
      const response = await fetch(
        `${API_BASE}/graph/communities?source=${source}&window=${windowSize}`
      )
      
      if (!response.ok) {
        if (response.status === 401) {
          openLogin && openLogin()
          throw new Error('该模块需要登录后访问')
        }
        if (response.status === 403) {
          openMembership && openMembership()
          throw new Error('非会员仅可访问「文献上新」图谱')
        }
        if (response.status === 404) {
          throw new Error('数据正在生成中，请稍后再试')
        }
        throw new Error(`HTTP ${response.status}`)
      }
      
      const data = await response.json()
      const items = data.items || []
      const snap = data.snapshot || null
      setCommunities(items)
      setSnapshot(snap)
      setGlobalKeywords(aggregateKeywords(items))
      setPopover(null)

      // 写入缓存（按source+window）
      setGraphCache((prev) => ({
        ...prev,
        [key]: {
          communities: items,
          snapshot: snap
        }
      }))

      // 自动为 Top5 社区预生成 WiW（仅在有 snapshot_id 时）
      if (snap && snap.snapshot_id && items.length > 0) {
        const topForWiw = getTopCommunities(items).slice(0, 5)
        topForWiw.forEach((comm) => {
          if (comm && comm.community_id) {
            loadWiwInternal(snap.snapshot_id, comm.community_id, key)
          }
        })
      }

      // 渲染社区气泡图
      if (items && items.length > 0) {
        renderCommunityGraph(items)
      }
    } catch (err) {
      setError(err.message)
      console.error('Failed to load graph:', err)
    } finally {
      setLoading(false)
    }
  }

  const renderCommunityGraph = (communitiesData) => {
    if (!chartRef.current) {
      console.error('Chart container not ready')
      return
    }
    
    // 确保在下一帧渲染，等待DOM完全挂载
    setTimeout(() => {
      if (chartInstance.current) {
        chartInstance.current.dispose()
        chartInstance.current = null
      }
      
      console.log(`Rendering ${communitiesData.length} communities with ECharts`)
      
      // 使用像素风格方块
      const nodes = recommendedPixelStyle(communitiesData)
      
      // 初始化ECharts
      chartInstance.current = echarts.init(chartRef.current)
      
      const option = {
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'item',
          backgroundColor: 'rgba(0, 0, 0, 0.85)',
          borderColor: 'rgba(255, 255, 255, 0.2)',
          borderWidth: 1,
          textStyle: { color: '#ffffff', fontSize: 13 },
          formatter: (params) => {
            if (params.dataType === 'node') {
              const comm = params.data.communityData
              return `
                <div style="padding: 8px;">
                  <div style="font-weight: bold; margin-bottom: 6px; color: #6b73ff;">${params.data.name}</div>
                  <div style="font-size: 12px;">
                    文献数量: <strong>${comm.size}</strong><br/>
                    活跃度: <strong>${(comm.activity * 100).toFixed(0)}%</strong>
                  </div>
                </div>
              `
            }
            return ''
          }
        },
        series: [{
          type: 'graph',
          layout: 'force',
          data: nodes,
          links: [], // 社区气泡图无边
          categories: [
            { name: 'Group 1' },
            { name: 'Group 2' },
            { name: 'Group 3' },
            { name: 'Group 4' }
          ],
          roam: true,
          draggable: true,
          label: {
            show: true,
            position: 'inside',
            fontSize: 11,
            fontWeight: 'bold'
          },
          force: {
            repulsion: 1200,
            gravity: 0.05,
            edgeLength: 200,
            layoutAnimation: true,
            friction: 0.4
          },
          emphasis: {
            focus: 'adjacency',
            itemStyle: {
              borderWidth: 4,
              borderColor: '#ffffff',
              shadowBlur: 25,
              shadowColor: 'rgba(107, 115, 255, 0.6)'
            },
            label: {
              fontSize: 13,
              fontWeight: 'bold'
            }
          }
        }]
      }
      
      chartInstance.current.setOption(option)
      
      // 多次调用resize确保正确尺寸
      setTimeout(() => {
        if (chartInstance.current) {
          chartInstance.current.resize()
        }
      }, 50)
      
      setTimeout(() => {
        if (chartInstance.current) {
          chartInstance.current.resize()
        }
      }, 200)
      
      // 点击事件（通过 id 从当前数据源查找，避免ECharts复制data导致的丢失）
      chartInstance.current.on('click', (params) => {
        // 计算相对图容器的坐标（使用 clientX/clientY 与容器 bounding rect）
        const ev = params && params.event
        const dom = containerRef.current
        const rect = dom ? dom.getBoundingClientRect() : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight }
        const clientX = ev && ev.event && (ev.event.clientX ?? ev.event.x)
        const clientY = ev && ev.event && (ev.event.clientY ?? ev.event.y)
        let ox = (typeof clientX === 'number') ? (clientX - rect.left) : undefined
        let oy = (typeof clientY === 'number') ? (clientY - rect.top) : undefined
        const containerWidth = (rect.width || (dom && dom.clientWidth) || 0)
        const containerHeight = (rect.height || (dom && dom.clientHeight) || 0)
        
        if (params.dataType === 'node') {
          const id = params.data && (params.data.id || params.data.name)
          const comm = communitiesData.find(c => c.community_id === id) || params.data.communityData
          if (comm && typeof ox === 'number' && typeof oy === 'number') {
            // 仅弹出就地卡片，避免布局切换导致图谱抖动
            setSelectedCommunity(null)
            setFilteredKeyword(null)
            
            // 决定左/右放置：点击位置在容器左半部分则右侧弹出，否则左侧弹出
            const place = ox < containerWidth * 0.5 ? 'right' : 'left'
            
            // 固定Y位置为容器垂直居中，确保卡片不会浮到屏幕外
            const centerY = containerHeight * 0.5
            
            setPopover({ x: ox, y: centerY, place, community: comm })
          }
        } else {
          // 点击画布空白处，关闭弹出卡片
          setPopover(null)
        }
      })
    }, 0) // setTimeout结束
  }

  // 弹出卡片位置自适应，确保完全在容器内且正左或正右
  useEffect(() => {
    if (!popover) return
    const dom = containerRef.current
    const pop = popoverRef.current
    if (!dom || !pop) return

    const clamp = () => {
      const crect = dom.getBoundingClientRect()
      const prect = pop.getBoundingClientRect()
      const pad = 20
      let { x, y, place } = popover
      const cW = crect.width || dom.clientWidth || 0
      const cH = crect.height || dom.clientHeight || 0

      // 确保卡片完全在垂直范围内（正中间对齐）
      const minY = pad + prect.height / 2
      const maxY = cH - pad - prect.height / 2
      y = Math.min(Math.max(y, minY), maxY)

      // 根据place确保卡片在水平方向不溢出
      const popoverWidth = prect.width
      const gap = 20 // 卡片与点击点的间距
      
      if (place === 'right') {
        // 右侧弹出：确保右边界不超出
        if (x + gap + popoverWidth > cW - pad) {
          // 空间不够，切换到左侧
          place = 'left'
        }
      }
      
      if (place === 'left') {
        // 左侧弹出：确保左边界不超出
        if (x - gap - popoverWidth < pad) {
          // 空间不够，切换到右侧
          place = 'right'
        }
      }

      // 微调X位置确保在边界内
      if (place === 'right') {
        const maxX = cW - pad - popoverWidth - gap
        x = Math.min(x, maxX)
      } else {
        const minX = pad + popoverWidth + gap
        x = Math.max(x, minX)
      }

      if (Math.abs(x - popover.x) > 0.5 || Math.abs(y - popover.y) > 0.5 || place !== popover.place) {
        setPopover(prev => ({ ...prev, x, y, place }))
      }
    }

    clamp()
    const handler = () => clamp()
    window.addEventListener('resize', handler, { passive: true })
    window.addEventListener('scroll', handler, { passive: true })
    return () => {
      window.removeEventListener('resize', handler)
      window.removeEventListener('scroll', handler)
    }
  }, [popover])

  return (
    <div className="knowledge-graph-page">
      <header className={styles.pageHeader}>
        <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>热点图谱</h1>
        <TypewriterSubtitle
          text={[
            '聚类算法精准捕捉近期热点关键词！',
            '每日更新，让您像追星一样追逐领域热点！',
          ]}
          active={titleVisible}
        />
      </header>

      {authSession && isGuest && (
        <div style={{ padding: '16px' }}>
          <p style={{ marginBottom: '12px' }}>该模块需要登录后访问</p>
          <button
            type="button"
            className="qq-login-entry"
            onClick={() => openLogin && openLogin()}
            aria-label="QQ登录"
          >
            <img src="/qq-login.png" alt="QQ登录" className="qq-login-img" draggable="false" />
          </button>
        </div>
      )}

      {authSession && !isGuest && !isMember && (
        <div style={{ padding: '0 16px 12px', color: '#666', fontSize: '14px' }}>
          非会员仅可访问「文献上新」图谱；其他数据源需要会员解锁
        </div>
      )}
      
      <div className={styles.controlsBar}>
        <select 
          value={selectedSource} 
          onChange={(e) => setSelectedSource(e.target.value)}
          className={styles.kgSelect}
          disabled={!authSession || isGuest}
        >
          <option value="literature">文献上新</option>
          <option value="sports_journals" disabled={!isMember}>运动科学顶刊</option>
          <option value="cns" disabled={!isMember}>CNS综合顶刊</option>
        </select>
        
        <select 
          value={selectedWindow} 
          onChange={(e) => setSelectedWindow(e.target.value)}
          className={styles.kgSelect}
          disabled={!authSession || isGuest}
        >
          {/* 仅文献上新支持1天窗口；顶刊类从7天起步 */}
          {selectedSource === 'literature' && <option value="1d">最近1天</option>}
          <option value="7d">最近7天</option>
          <option value="30d">最近30天</option>
          <option value="180d">最近半年</option>
        </select>
        
        <button
          onClick={() => loadGraph(selectedSource, selectedWindow, { force: true })}
          className={styles.refreshBtn}
          disabled={!authSession || isGuest}
        >
          刷新
        </button>
      </div>

      {snapshot && (
        <div className={styles.snapshotInfo}>
          <div className={styles.stat}>
            <span className={styles.statLabel}>数据源</span>
            <span className={styles.statValue}>
              {selectedSource === 'literature' ? '文献上新' : 
               selectedSource === 'sports_journals' ? '运动科学顶刊' : 'CNS综合顶刊'}
            </span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statLabel}>时间窗口</span>
            <span className={styles.statValue}>{selectedWindow}</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statLabel}>社区数</span>
            <span className={styles.statValue}>{communities.length}</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statLabel}>更新时间</span>
            <span className={styles.statValue}>{snapshot.as_of || 'N/A'}</span>
          </div>
        </div>
      )}

      {loading && (
        <div className={styles.loading}>
          <div className={styles.spinner}></div>
          <p>加载图谱数据中...</p>
        </div>
      )}

      {error && (
        <div className={styles.errorMessage}>
          <p>加载失败: {error}</p>
          <button onClick={loadGraph} className={styles.retryBtn}>重试</button>
        </div>
      )}

      <div className={styles.mainContent}>
        {/* ECharts图谱容器 */}
        <div className={styles.graphContainer} ref={containerRef} style={{ 
          display: loading || error ? 'none' : 'flex',
          minHeight: '800px'
        }}>
          <div ref={chartRef} className={styles.chartCanvas}></div>
          {/* 气泡就地弹出卡片 */}
	          {popover && (
	            <div 
	              className={`${styles['kg-popover']} ${popover.place === 'left' ? styles['kgPopoverLeft'] : styles['kgPopoverRight']}`} 
	              style={{ left: popover.x, top: popover.y }}
              onClick={(e) => e.stopPropagation()}
              ref={popoverRef}
            >
	              <div className={styles['kg-popover-header']}>
	                <h5 className={styles['kg-popover-title']}>
	                  {getCommunityTitle(popover.community)}
	                </h5>
	                <button className={styles['kg-popover-close']} onClick={() => setPopover(null)}>×</button>
	              </div>
	              <div className={styles['kg-popover-body']}>
                <div className={styles['kg-popover-row']}>
                  <span>文献数量</span>
                  <strong>{(() => { const all = popover.community.top_papers || []; const kw = (filteredKeyword || '').trim(); const list = kw ? all.filter(p => paperMatchesKeyword(p, kw)) : all; return list.length })()}</strong>
	                </div>
	                {/* 候选术语 chips（来自 representative_terms） */}
	                <div className={styles['kg-popover-chips']}>
	                  {(() => {
	                    const papers = popover.community.top_papers || []
	                    const rawTerms = Array.isArray(popover.community.representative_terms)
	                      ? popover.community.representative_terms
	                      : []
	
	                    const seen = new Set()
	                    const available = []
	                    for (const it of rawTerms) {
	                      const raw = typeof it === 'string' ? it : (it?.term || '')
	                      if (!raw) continue
	                      const normalized = normalizeTermClient(raw)
	                      if (!isValidTermClient(normalized)) continue
	                      if (seen.has(normalized)) continue
	                      seen.add(normalized)
	
	                      let hits = 0
	                      for (const p of papers) {
	                        if (paperMatchesKeyword(p, normalized)) hits += 1
	                        if (hits >= 2) break
	                      }
	                      if (hits < 2) continue
	
	                      available.push({ raw, normalized })
	                      if (available.length >= 6) break
	                    }
	
	                    if (!available.length) return null
	                    return available.map((t, i) => (
	                      <span
	                        key={`${t.normalized}-${i}`}
	                        className={styles['kg-chip']}
	                        onClick={() => setFilteredKeyword(t.normalized)}
	                      >
	                        {t.raw}
	                      </span>
	                    ))
	                  })()}
	                </div>
	                {/* Top 10 论文（按时间排序） */}
	                <div className={styles['kg-popover-papers']}>
                  {(() => {
                    const all = popover.community.top_papers || []
                    const kw = (filteredKeyword || '').trim()
                    let list = kw
                      ? all.filter(p => paperMatchesKeyword(p, kw))
                      : all
                    
                    // 如果超过10篇，按时间排序取最新10篇
                    if (list.length > 10) {
                      list = [...list].sort((a, b) => {
                        const dateA = a.pub_date || ''
                        const dateB = b.pub_date || ''
                        return dateB.localeCompare(dateA) // 降序：最新的在前
                      }).slice(0, 10)
                    }
                    
                    return list.map((p, i) => {
                      const pmid = p.pmid || ''
                      const isDoi = typeof pmid === 'string' && pmid.toLowerCase().startsWith('doi:')
                      const href = isDoi
                        ? `https://doi.org/${encodeURIComponent(pmid.slice(4))}`
                        : `https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(pmid)}/`
                      return (
                        <div key={i} className={styles['kg-popover-paper']}>
                          <a href={href} target="_blank" rel="noopener noreferrer">
                            {p.title}
                            {p.pub_date && <span style={{fontSize: '11px', color: '#6b7280', marginLeft: '6px'}}>({p.pub_date.slice(0, 10)})</span>}
                          </a>
                        </div>
                      )
                    })
                  })()}
                </div>
              </div>
              <div className={styles['kg-popover-arrow']}></div>
            </div>
          )}
        </div>
        {/* 关键词面板（图谱下方） - 优化分层显示 */}
        {!loading && !error && globalKeywords.length > 0 && (
          <div className={styles['kg-keywords-panel']}>
            <div style={{ 
              marginBottom: '14px', 
              fontWeight: 700, 
              fontSize: '16px',
              color: '#2d2d2d',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontFamily: 'BoutiqueBitmap, monospace'
            }}>
              <span>🏷️</span>
              <span>高频关键词 & 社区摘要</span>
              <span style={{ fontSize: '12px', fontWeight: 500, color: '#8b7355' }}>(点击关键词跳转相关社区)</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
              {(() => {
                // globalKeywords已按权重降序排列，直接使用
                const allKws = globalKeywords
                if (!allKws.length) return null

                // 动态计算层级阈值（基于权重分布）
                const weights = allKws.map(k => k.weight || 0)
                const p75 = weights[Math.floor(weights.length * 0.20)] || 0  // Top 20%
                const p50 = weights[Math.floor(weights.length * 0.45)] || 0  // Top 45%

                const tier1 = allKws.filter(k => (k.weight || 0) >= p75)  // 高频核心
                const tier2 = allKws.filter(k => (k.weight || 0) >= p50 && (k.weight || 0) < p75)  // 中频重要
                const tier3 = allKws.filter(k => (k.weight || 0) < p50).slice(0, 20)  // 长尾（限制20个）

                const renderTier = (items, label, tone) => {
                  if (!items.length) return null
                  return (
                    <div style={{ marginBottom: '12px' }}>
                      <div style={{
                        fontSize: '12px',
                        color: '#2d2d2d',
                        marginBottom: '6px',
                        fontWeight: 600,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontFamily: 'BoutiqueBitmap, monospace'
                      }}>
                        {label}
                        <span style={{ fontSize: '11px', color: '#8b7355' }}>({items.length}个)</span>
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                        {items.map(({ term, weight, count }) => (
                          <span
                            key={term}
                            className={styles['kg-chip']}
                            style={{
                              fontSize: '11px',
                              padding: '4px 10px',
                              cursor: 'pointer',
                              fontFamily: 'BoutiqueBitmap, monospace'
                            }}
                            title={`出现于${count}个社区 | 权重 ${Number.isFinite(weight) ? weight.toFixed(2) : '1.00'}`}
                            onClick={() => openPopoverForKeyword(term)}
                          >
                            <span style={{ color: '#2d2d2d' }}>{term}</span>
                            <span style={{ marginLeft: 6, fontSize: '10px', color: '#8b7355' }}>×{count}</span>
                            {/* 高权重点不再用表情标记，保持视觉简洁 */}
                          </span>
                        ))}
                      </div>
                    </div>
                  )
                }
                return (
                  <>
                    {renderTier(tier1, '核心关键词', {})}
                    {renderTier(tier2, '重要关键词', {})}
                    {renderTier(tier3, '长尾关键词', {})}
                  </>
                )
              })()}
              {getTopCommunities().length > 0 && (
                <div style={{ borderTop: '2px solid #8b7355', paddingTop: '12px', marginTop: '12px' }}>
                  <div style={{
                    fontSize: '13px',
                    color: '#2d2d2d',
                    marginBottom: '8px',
                    fontWeight: 600,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontFamily: 'BoutiqueBitmap, monospace'
                  }}>
                    <span>当前板块 Top5 社区摘要</span>
                    <button
                      onClick={() => {
                        if (expandedComms.size === 5) {
                          setExpandedComms(new Set())  // 全部折叠
                        } else {
                          setExpandedComms(new Set([0,1,2,3,4]))  // 全部展开
                        }
                      }}
                      style={{
                        padding: '4px 10px',
                        background: 'transparent',
                        border: '2px solid #8b7355',
                        borderRadius: '0',
                        color: '#2d2d2d',
                        fontSize: '11px',
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                        boxShadow: '2px 2px 0 0 #1a1a1a',
                        fontFamily: 'BoutiqueBitmap, monospace'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.transform = 'translateY(-1px)'
                        e.currentTarget.style.boxShadow = '3px 3px 0 0 #1a1a1a'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.transform = ''
                        e.currentTarget.style.boxShadow = '2px 2px 0 0 #1a1a1a'
                      }}
                    >
                      {expandedComms.size === 5 ? '全部折叠' : '全部展开'}
                    </button>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
	                    {getTopCommunities().map((comm, idx) => {
                      const rank = idx + 1
                      const isTop5 = rank <= 5
                      const isExpanded = expandedComms.has(idx)
	                      const title =
	                        getCommunityTitle(comm)
                      const summaryText = (comm.summary || '').trim()
                      const shortSummary =
                        summaryText.length > 120 ? summaryText.slice(0, 120) + '…' : summaryText
                      const terms = (comm.representative_terms || []).slice(0, 4)
                      const wiw = wiwState[comm.community_id] || {}
                      return (
                        <div
                          key={comm.community_id}
                          style={{
                            padding: '10px 12px',
                            borderRadius: 0,
                            background: 'transparent',
                            border: '2px solid #8b7355',
                            boxShadow: isTop5 ? '3px 3px 0 0 #1a1a1a' : '2px 2px 0 0 #1a1a1a',
                            transition: 'all 0.2s ease'
                          }}
                        >
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              marginBottom: 4,
                              cursor: 'pointer',
                              userSelect: 'none'
                            }}
                            onClick={() => {
                              const newExpanded = new Set(expandedComms)
                              if (newExpanded.has(idx)) {
                                newExpanded.delete(idx)
                              } else {
                                newExpanded.add(idx)
                              }
                              setExpandedComms(newExpanded)
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span style={{
                                fontSize: '14px',
                                transition: 'transform 0.2s ease',
                                transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                                color: '#2d2d2d'
                              }}>▶</span>
                              <span style={{ fontSize: '11px', color: '#8b7355', fontFamily: 'BoutiqueBitmap, monospace' }}>#{rank}</span>
                              <span style={{ fontSize: '13px', fontWeight: 600, color: '#2d2d2d', fontFamily: 'BoutiqueBitmap, monospace' }}>{title}</span>
                              <span style={{ fontSize: '11px', color: '#8b7355', fontFamily: 'BoutiqueBitmap, monospace' }}>
                                · {comm.size} 篇 · {(comm.activity * 100).toFixed(0)}% 活跃
                              </span>
                            </div>
                            {isTop5 && (
                              <span style={{ fontSize: '11px', color: '#8b7355', fontFamily: 'BoutiqueBitmap, monospace' }}>
                                {wiw.loading
                                  ? '社区摘要生成中…'
                                  : wiw.text
                                  ? '社区摘要已生成'
                                  : wiw.error
                                  ? '社区摘要生成失败'
                                  : '社区摘要就绪'}
                              </span>
                            )}
                          </div>

                          {/* 展开时显示术语chips */}
                          {isExpanded && terms.length > 0 && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: 6 }}>
                              {terms.map((t, i) => (
                                <span
                                  key={i}
                                  className={styles['kg-chip']}
                                  style={{
                                    fontSize: '10px',
                                    padding: '2px 8px',
                                    cursor: 'pointer',
                                    fontFamily: 'BoutiqueBitmap, monospace'
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    openPopoverForKeyword(t.term)
                                  }}
                                >
                                  {t.term}
                                </span>
                              ))}
                            </div>
                          )}

                          {/* 展开时显示完整摘要，折叠时显示简短摘要 */}
                          {summaryText && (
                            <div style={{ fontSize: '12px', lineHeight: 1.5, color: '#2d2d2d', fontFamily: '-apple-system, sans-serif' }}>
                              {isExpanded ? summaryText : shortSummary}
                            </div>
                          )}

                          {/* 展开时显示WiW分析 */}
                          {isExpanded && wiw.text && (
                            <div
                              style={{
                                marginTop: 6,
                                paddingTop: 6,
                                borderTop: '2px solid #8b7355',
                                fontSize: '12px',
                                lineHeight: 1.5,
                                color: '#2d2d2d',
                                fontFamily: '-apple-system, sans-serif'
                              }}
                            >
                              <div style={{ fontSize: '11px', color: '#8b7355', marginBottom: 4, fontFamily: 'BoutiqueBitmap, monospace' }}>社区摘要</div>
                              <div>{renderWiwWithLinks(wiw)}</div>
                              {Array.isArray(wiw.citations) && wiw.citations.length > 0 && (
                                <div
                                  style={{
                                    marginTop: 8,
                                    paddingTop: 6,
                                    borderTop: '2px solid #8b7355',
                                    fontSize: '11px',
                                    lineHeight: 1.5,
                                    color: '#2d2d2d'
                                  }}
                                >
                                  <div style={{ color: '#8b7355', marginBottom: 2, fontFamily: 'BoutiqueBitmap, monospace' }}>参考文献</div>
                                  {wiw.citations.map((c) => {
                                    if (!c || typeof c.index !== 'number') return null
                                    const idx = c.index
                                    const papers = comm.top_papers || []
                                    const paper = papers[idx - 1] || {}
                                    const title = paper.title || c.url || ''
                                    const href = c.url || null
                                    return (
                                      <div key={`ref-${comm.community_id}-${idx}`} style={{ marginBottom: 2 }}>
                                        <span style={{ color: '#8b7355' }}>[文献{idx}] </span>
                                        {href ? (
                                          <a
                                            href={href}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            style={{ color: '#6b73ff', textDecoration: 'underline' }}
                                          >
                                            {title}
                                          </a>
                                        ) : (
                                          <span>{title || '（标题缺失）'}</span>
                                        )}
                                      </div>
                                    )
                                  })}
                                </div>
                              )}
                            </div>
                          )}

                          {/* WiW错误信息 */}
                          {isExpanded && wiw.error && (
                            <div style={{ marginTop: 4, fontSize: '11px', color: '#c97a63', fontFamily: 'BoutiqueBitmap, monospace' }}>
                              WiW生成失败：{wiw.error}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
