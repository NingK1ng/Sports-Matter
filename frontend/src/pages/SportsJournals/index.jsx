import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import TypewriterSubtitle from '../../components/TypewriterSubtitle'
import styles from './SportsJournals.module.css'

const API_BASE = '/api/v1/sports-journals'

// 构造更稳定的PubMed检索词：优先使用ISSN，其次用期刊名，使用 [Journal] 字段
const buildPubmedTerm = (journal) => {
  if (!journal) return ''
  const issn = (journal.issn || '').trim()
  if (issn) return `"${issn}"[Journal]`
  const name = (journal.name || '').trim()
  if (name) return `"${name}"[Journal]`
  return ''
}

const TREND_YEARS = ['2020', '2021', '2022', '2023', '2024', '2025']
const ISSN_RE = /\b\d{4}-\d{3}[\dXx]\b/g
const SPORTS_SCIENCE_NO_TREND_ISSNS = new Set(['0306-3674', '0363-5465', '0112-1642', '0195-9131'])

const extractIssnParam = (raw) => {
  const s = (raw || '').toString()
  const found = s.match(ISSN_RE)
  if (found && found.length > 0) {
    return Array.from(new Set(found.map((x) => x.toUpperCase()))).join(',')
  }
  return s.trim()
}

const buildJournalIssnParam = (journal) => {
  const aliases = journal && Array.isArray(journal.issn_aliases) ? journal.issn_aliases : null
  if (aliases && aliases.length > 0) {
    return aliases.map((x) => String(x || '').trim().toUpperCase()).filter(Boolean).join(',')
  }
  return extractIssnParam(journal?.issn)
}

function JournalYearTrend({ yearlyCounts }) {
  const values = useMemo(() => {
    const m = yearlyCounts && typeof yearlyCounts === 'object' ? yearlyCounts : {}
    return TREND_YEARS.map((y) => Number(m[y] ?? 0) || 0)
  }, [yearlyCounts])

  const max = Math.max(...values, 1)
  const w = 420
  const h = 120
  const padX = 18
  const padTop = 18
  const padBottom = 26
  const innerW = w - padX * 2
  const innerH = h - padTop - padBottom
  const gap = 8
  const barW = Math.max(10, Math.floor((innerW - gap * (values.length - 1)) / values.length))

  const hasAny = values.some((v) => v > 0)

  return (
    <div className={styles.journalTrendCard} aria-label="年文章数趋势图">
      <div className={styles.journalTrendTitle}>"文献上新"板块年文章数趋势（2020-2025）</div>
      {hasAny ? (
        <svg
          width="100%"
          height={h}
          viewBox={`0 0 ${w} ${h}`}
          role="img"
          aria-label="年文章数柱状趋势图"
        >
          <rect x="0" y="0" width={w} height={h} fill="transparent" />
          {values.map((v, i) => {
            const x = padX + i * (barW + gap)
            const barH = Math.max(2, Math.round((v / max) * innerH))
            const y = padTop + (innerH - barH)
            const year = TREND_YEARS[i]
            const labelY = Math.max(y - 6, 12)
            return (
              <g key={year}>
                <title>
                  {year}: {v}
                </title>
                <text
                  x={x + barW / 2}
                  y={labelY}
                  textAnchor="middle"
                  fontSize="10"
                  fill="#2d2d2d"
                  fontFamily="BoutiqueBitmap, monospace"
                >
                  {v}
                </text>
                <rect
                  x={x}
                  y={y}
                  width={barW}
                  height={barH}
                  rx="2"
                  fill="rgba(232, 215, 185, 0.75)"
                  stroke="#8b7355"
                  strokeWidth="2"
                />
                <text
                  x={x + barW / 2}
                  y={h - 10}
                  textAnchor="middle"
                  fontSize="10"
                  fill="#2d2d2d"
                  fontFamily="BoutiqueBitmap, monospace"
                >
                  {year.slice(2)}
                </text>
              </g>
            )
          })}
        </svg>
      ) : (
        <div className={styles.journalTrendEmpty}>暂无趋势数据</div>
      )}
    </div>
  )
}

function SportsJournals() {
  const navigate = useNavigate()
  const outlet = useOutletContext()
  const authSession = outlet?.authSession
  const openLogin = outlet?.openLogin
  const openMembership = outlet?.openMembership

  const isGuest = Boolean(authSession?.user?.is_guest || authSession?.user?.nickname === '访客' || authSession?.user?.nickname === '游客')
  const isMember = Boolean(authSession?.user?.is_member)

  const [q, setQ] = useState('')
  const [casPartition, setCasPartition] = useState('all')
  const [oaType, setOaType] = useState('all')
  const [category, setCategory] = useState('sports_science')
  const [page, setPage] = useState(1)
  const [perPage] = useState(10)
  const [data, setData] = useState({ total: 0, page: 1, pages: 0, items: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [detailsCache, setDetailsCache] = useState({})
  const [titleVisible, setTitleVisible] = useState(false)

  // 标题淡入
  useEffect(() => {
    const timer = setTimeout(() => setTitleVisible(true), 300)
    return () => clearTimeout(timer)
  }, [])

  // 根据筛选和页码加载列表（模仿文献上新逻辑）
  useEffect(() => {
    if (!authSession) return
    if (isGuest) return
    if (!isMember && category === 'high_volume') {
      setCategory('sports_science')
      setPage(1)
      return
    }
    const run = async () => {
      setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams()
        if (q.trim()) params.set('q', q.trim())
        if (casPartition !== 'all') params.set('cas_partition', casPartition)
        if (oaType !== 'all') params.set('oa_type', oaType)
        if (category) params.set('category', category)
        params.set('page', String(page))
        params.set('per_page', String(perPage))

        const res = await fetch(`${API_BASE}/list?${params.toString()}`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        setData(json)
      } catch (err) {
        console.error('Failed to fetch sports journals:', err)
        setError('加载失败，请稍后重试')
        setData({ total: 0, page: 1, pages: 0, items: [] })
      } finally {
        setLoading(false)
      }
    }

    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authSession, isGuest, page, casPartition, oaType, category])

  const handleSearch = async () => {
    setPage(1)
    // 触发useEffect重新拉取
    const params = new URLSearchParams()
    if (q.trim()) params.set('q', q.trim())
    if (casPartition !== 'all') params.set('cas_partition', casPartition)
    if (oaType !== 'all') params.set('oa_type', oaType)
    if (category) params.set('category', category)
    params.set('page', '1')
    params.set('per_page', String(perPage))
    try {
      setLoading(true)
      setError(null)
      const res = await fetch(`${API_BASE}/list?${params.toString()}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
    } catch (err) {
      console.error('Failed to fetch sports journals:', err)
      setError('加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  const loadDetail = async (id) => {
    if (detailsCache[id]) return
    try {
      const res = await fetch(`${API_BASE}/${id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setDetailsCache((prev) => ({ ...prev, [id]: json }))
    } catch (err) {
      console.error('Failed to fetch journal detail:', err)
    }
  }

  const toggleExpand = async (id) => {
    if (expandedId === id) {
      setExpandedId(null)
      return
    }
    await loadDetail(id)
    setExpandedId(id)
  }

  const totalPages = data.pages || 0

  if (!authSession) {
    return (
      <div className={styles.literatureStream}>
        <header className={styles.pageHeader}>
          <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>
            运动科学期刊
          </h1>
          <TypewriterSubtitle
            text={['加载中...']}
            active={titleVisible}
          />
        </header>
      </div>
    )
  }

  if (isGuest) {
    return (
      <div className={styles.literatureStream}>
        <header className={styles.pageHeader}>
          <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>
            运动科学期刊
          </h1>
          <TypewriterSubtitle
            text={['该模块需要登录后访问']}
            active={titleVisible}
          />
        </header>
        <div style={{ padding: '16px' }}>
          <button
            type="button"
            className="qq-login-entry"
            onClick={() => openLogin && openLogin()}
            aria-label="QQ登录"
          >
            <img
              src="/qq-login.png"
              alt="QQ登录"
              className="qq-login-img"
              draggable="false"
            />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.literatureStream}>
      <header className={styles.pageHeader}>
        <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>
          运动科学期刊
        </h1>
        <TypewriterSubtitle
          text={[
            '运动科学专刊，还是领域发文多的综合期刊？',
            '您的文章可能值得更好的去处！'
          ]}
          active={titleVisible}
        />
      </header>

      {/* 筛选区：完全复用文献上新的像素卡片风格 */}
      <div className={styles.filtersCard}>
        <div className={styles.filterGroup}>
          <label>关键词搜索</label>
          <div className={styles.searchRow}>
            <input
              type="text"
              placeholder="输入期刊名或ISSN..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSearch()
              }}
            />
            <div className={styles.filterActions}>
              <button type="button" onClick={handleSearch}>
                搜索
              </button>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => {
                  setQ('')
                  setCasPartition('all')
                  setOaType('all')
                  setCategory('sports_science')
                  setPage(1)
                }}
              >
                重置
              </button>
            </div>
          </div>
        </div>

        <div className={styles.filterGroup}>
          <label>中科院分区</label>
          <select
            value={casPartition}
            onChange={(e) => {
              setPage(1)
              setCasPartition(e.target.value)
            }}
          >
            <option value="all">全部</option>
            <option value="1">1区</option>
            <option value="2">2区</option>
            <option value="3">3区</option>
            <option value="4">4区</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label>OA 类型</label>
          <select
            value={oaType}
            onChange={(e) => {
              setPage(1)
              setOaType(e.target.value)
            }}
          >
            <option value="all">全部</option>
            <option value="oa">纯OA期刊</option>
            <option value="non_oa">非OA期刊</option>
            <option value="hybrid">Hybrid OA</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label>期刊类别</label>
          <select
            value={category}
            onChange={(e) => {
              const next = e.target.value
              if (next === 'high_volume' && !isMember) {
                openMembership && openMembership()
                return
              }
              setPage(1)
              setCategory(next)
            }}
          >
            <option value="sports_science">运动科学专刊</option>
            <option value="high_volume">
              文献上新高频期刊{!isMember ? '（会员）' : ''}
            </option>
          </select>
        </div>
      </div>

      {/* 列表部分，复用文献上新的卡片样式 */}
      {loading ? (
        <div className={styles.emptyState}>加载中...</div>
      ) : error ? (
        <div className={styles.errorMessage}>
          <span className={styles.errorIcon}>⚠️</span>
          <p>{error}</p>
          <button onClick={handleSearch} className={styles.retryButton}>
            重试
          </button>
        </div>
      ) : data.items.length === 0 ? (
        <div className={styles.emptyState}>暂无匹配的期刊</div>
      ) : (
        <>
          <div className={styles.articlesList}>
            {data.items.map((j, index) => {
              const detail = detailsCache[j.id]
              const expanded = expandedId === j.id
              const issnParam = buildJournalIssnParam(j)

              const hasBasicInfo = detail && (
                detail.official_site ||
                detail.submission_site ||
                detail.guidelines_site
              )

              // 仅保留以下指标：出版商、出版周期、Gold OA比例、研究类文章比例
              const hasMetrics = detail && (
                detail.publisher ||
                detail.publish_frequency ||
                detail.gold_oa_percent != null ||
                detail.research_article_percent != null
              )

              return (
                <div key={j.id} className={styles.articleItem}>
                  <div className={styles.journalRow}>
                    <div className={styles.journalMain}>
                      <div className={styles.articleTitle} onClick={() => toggleExpand(j.id)}>
                        <span>{j.name}</span>
                        <span className={styles.metaJournal}>ISSN: {j.issn}</span>
                      </div>

                      <div className={styles.articleMeta}>
                        {(() => {
                          const q = (j.wos_jif_quartile || '').trim()
                          const show = /^Q[1-4]/i.test(q)
                          return show ? (
                            <>
                              <span className={styles.metaSeparator}>·</span>
                              <span className={styles.metaJournal}>JIF {q.toUpperCase()}</span>
                            </>
                          ) : null
                        })()}
                      </div>

                      <div className={styles.articleTags}>
                        {j.category && (
                          <span className={`${styles.tag} ${styles.tagCategory}`}>
                            {j.category === 'sports_science'
                              ? '运动科学专刊'
                              : j.category === 'high_volume'
                                ? '文献上新高频期刊'
                                : j.category}
                          </span>
                        )}
                        {j.cas_partition && (
                          <span className={`${styles.tag} ${styles.tagZone}`}>
                            中科院{j.cas_partition}
                          </span>
                        )}
                        {(() => {
                          const q = (j.wos_jif_quartile || '').trim()
                          const show = /^Q[1-4]/i.test(q)
                          return show ? (
                            <span className={`${styles.tag} ${styles.tagIf}`}>
                              JIF {q.toUpperCase()}
                            </span>
                          ) : null
                        })()}
                        {j.category === 'high_volume' && j.literature_count != null && j.literature_count > 0 && (
                          <button
                            type="button"
                            className={`${styles.tag} ${styles.tagLink}`}
                            onClick={() => {
                              if (!issnParam) return
                              navigate(`/literature?journal_issn=${encodeURIComponent(issnParam)}&window=730d`)
                            }}
                          >
                            最近两年相关文章数 {j.literature_count}
                          </button>
                        )}
                        {j.year_articles != null && j.year_articles > 0 && (
                          <span className={styles.tag}>年文章数 {j.year_articles}</span>
                        )}
                        {j.acceptance && (
                          <span className={styles.tag}>录用难度 {j.acceptance}</span>
                        )}
                        {j.review_time && (
                          <span className={styles.tag}>审稿周期 {j.review_time}</span>
                        )}
                        {j.is_oa && (
                          <span className={styles.tag}>OA类型 {j.is_oa}</span>
                        )}
                      </div>

                      <div className={styles.articleActions}>
                        <button
                          className={styles.toggleAbstract}
                          type="button"
                          onClick={() => toggleExpand(j.id)}
                        >
                          {expanded ? '收起详情 ▲' : '展开详情 ▼'}
                        </button>
                        <a
                          href={j.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.pubmedLink}
                        >
                          在 LetPub 查看期刊 →
                        </a>
                        <a
                          href={`https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(
                            buildPubmedTerm(j)
                          )}`}
                          target="_blank"
                          rel="noreferrer"
                          className={styles.pubmedLink}
                        >
                          在pubmed中检索此期刊 →
                        </a>
                      </div>
                    </div>

                    {!(
                      category === 'sports_science' &&
                      Array.isArray(j.issn_aliases) &&
                      j.issn_aliases.some((x) => SPORTS_SCIENCE_NO_TREND_ISSNS.has(String(x).toUpperCase()))
                    ) && (
                      <div className={styles.journalTrend}>
                        <JournalYearTrend yearlyCounts={j.yearly_counts} />
                      </div>
                    )}
                  </div>

                  {expanded && detail && (
                    <div className={styles.articleAbstract}>
                      {/* 如果完全没有数据，显示友好提示 */}
                      {!hasBasicInfo &&
                        !hasMetrics &&
                        (!detail.china_recent_papers || detail.china_recent_papers.length === 0) && (
                          <div
                            className={styles.emptyState}
                            style={{ padding: '20px', textAlign: 'center', color: '#999' }}
                          >
                            <p>📭 该期刊暂无详细信息</p>
                            <p style={{ fontSize: '14px', marginTop: '10px' }}>
                              LetPub尚未提供此期刊的详细数据，或数据抓取失败
                            </p>
                            <a
                              href={j.url}
                              target="_blank"
                              rel="noreferrer"
                              className={styles.pubmedLink}
                              style={{ marginTop: '15px', display: 'inline-block' }}
                            >
                              在 LetPub 查看期刊 →
                            </a>
                          </div>
                        )}

                      {hasBasicInfo && (
                        <div className={styles.abstractOriginal}>
                          <div className={styles.sectionHeader}>基础信息</div>
                          <div className={styles.sectionBody}>
                            {detail.official_site && (
                              <div>
                                期刊官网：
                                <a href={detail.official_site} target="_blank" rel="noreferrer">
                                  {detail.official_site}
                                </a>
                              </div>
                            )}
                            {detail.submission_site && (
                              <div>
                                投稿系统：
                                <a href={detail.submission_site} target="_blank" rel="noreferrer">
                                  {detail.submission_site}
                                </a>
                              </div>
                            )}
                            {detail.guidelines_site && (
                              <div>
                                作者指南：
                                <a href={detail.guidelines_site} target="_blank" rel="noreferrer">
                                  {detail.guidelines_site}
                                </a>
                              </div>
                            )}
                            {/* 按要求移除 PMC/NLM 显示 */}
                            {!detail.official_site &&
                              !detail.submission_site &&
                              !detail.guidelines_site && <div>（LetPub 暂未提供基础信息）</div>}
                          </div>
                        </div>
                      )}

                      {hasMetrics && (
                        <div className={styles.abstractOriginal}>
                          <div className={styles.sectionHeader}>期刊指标</div>
                          <div className={styles.sectionBody}>
                            {detail.publisher && <div>出版商：{detail.publisher}</div>}
                            {detail.publish_frequency && <div>出版周期：{detail.publish_frequency}</div>}
                            {detail.gold_oa_percent != null && (
                              <div>Gold OA比例：{detail.gold_oa_percent}%</div>
                            )}
                            {detail.research_article_percent != null && (
                              <div>研究类文章比例：{detail.research_article_percent}%</div>
                            )}
                            {!detail.publisher &&
                              !detail.publish_frequency &&
                              detail.gold_oa_percent == null &&
                              detail.research_article_percent == null && (
                                <div>（LetPub 暂未提供指标信息）</div>
                              )}
                          </div>
                        </div>
                      )}

                      {detail.china_recent_papers && detail.china_recent_papers.length > 0 && (
                        <div className={styles.abstractOriginal}>
                          <div className={styles.sectionHeader}>中国学者近期发文</div>
                          <ul className={styles.articleAbstractList}>
                            {detail.china_recent_papers.map((p, idx) => (
                              <li key={idx} className={styles.articleAbstractItem}>
                                <div className={styles.articleAbstractTitle}>
                                  {p.pubmed_url ? (
                                    <a
                                      href={p.pubmed_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className={styles.pubmedLink}
                                    >
                                      {p.title}
                                    </a>
                                  ) : (
                                    p.title
                                  )}
                                </div>
                              </li>
                            ))}
                          </ul>
                          <div className={styles.articleAbstractMeta}>
                            <a
                              href={j.url}
                              target="_blank"
                              rel="noreferrer"
                              className={styles.pubmedLink}
                            >
                              在 LetPub 查看全部中国学者发文 →
                            </a>
                            {' '}
                            <a
                              href={`https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(
                                buildPubmedTerm(j)
                              )}`}
                              target="_blank"
                              rel="noreferrer"
                              className={styles.pubmedLink}
                            >
                              在pubmed中检索此期刊 →
                            </a>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {totalPages > 1 ? (
            <div className={styles.paginationWrapper}>
              <button className={styles.pageButton} type="button" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>上一页</button>
              <span className={styles.pageInfo}>第 {page} / {totalPages} 页（共 {data.total} 本期刊）</span>
              <button className={styles.pageButton} type="button" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>下一页</button>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}

export default SportsJournals
