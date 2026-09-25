import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { literatureStreamAPI } from '../../services/api'
import Pagination from '../../components/Pagination'
import LoadingSpinner from '../../components/LoadingSpinner'
import TypewriterSubtitle from '../../components/TypewriterSubtitle'
import ArticleItem from './ArticleItem'
import styles from './LiteratureStream.module.css'

function LiteratureStream() {
  const [searchParams] = useSearchParams()
  const [articles, setArticles] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({
    category: '',
    lit_type: '',
    window: '30d',
    keywords: '',
    journal_issn: '',
    searchScope: 'tiab',
    topJournals: false,
    filterQuality: false,
    onlyZone1: false,
    zones: []
  })
  const [categories, setCategories] = useState([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [translating, setTranslating] = useState(false)
  const [titleVisible, setTitleVisible] = useState(false)
  const [initializedFromUrl, setInitializedFromUrl] = useState(false)

  useEffect(() => {
    fetchCategories()
    // 标题淡入动画
    setTimeout(() => {
      setTitleVisible(true)
    }, 300)
  }, [])

  useEffect(() => {
    if (initializedFromUrl) return
    const kwFromUrl = searchParams.get('kw')
    const issnFromUrl = searchParams.get('journal_issn')
    const windowFromUrl = searchParams.get('window')
    const hasAny = Boolean((kwFromUrl || '').trim() || (issnFromUrl || '').trim() || (windowFromUrl || '').trim())
    if (hasAny) {
      setFilters((prev) => ({
        ...prev,
        keywords: (kwFromUrl || '').trim() ? kwFromUrl : prev.keywords,
        journal_issn: (issnFromUrl || '').trim() ? issnFromUrl : prev.journal_issn,
        window: (windowFromUrl || '').trim() ? windowFromUrl : prev.window,
      }))
      setPage(1)
    }
    setInitializedFromUrl(true)
  }, [initializedFromUrl, searchParams, setFilters, setPage])

  useEffect(() => {
    // 防抖：关键词输入时延迟300ms再请求，其他筛选立即触发
    const debounceTimeout = filters.keywords ? setTimeout(() => {
      fetchArticles()
    }, 300) : null

    if (!filters.keywords) {
      fetchArticles()
    }

    return () => {
      if (debounceTimeout) clearTimeout(debounceTimeout)
    }
  }, [filters, page])

  const fetchCategories = async () => {
    try {
      const data = await literatureStreamAPI.fetchCategories()
      setCategories(data || [])
    } catch (e) {
      console.error('获取分类失败:', e)
    }
  }

  const fetchArticles = async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {
        page,
        per_page: 20,
      }
      if (filters.category) params.category = filters.category
      if (filters.lit_type) params.lit_type = filters.lit_type
      if (filters.window) params.window = filters.window
      if (filters.keywords) {
        params.keywords = filters.keywords
        params.search_scope = filters.searchScope
      }
      if (filters.journal_issn) params.journal_issn = filters.journal_issn
      if (filters.topJournals) params.top_journals = true
      if (filters.filterQuality) params.filter_quality = true
      if (filters.onlyZone1) params.only_zone1 = true
      if (filters.zones && filters.zones.length > 0) {
        params.zones = filters.zones.join(',')
      }

      const data = await literatureStreamAPI.fetchLiterature(params)
      setArticles(data.items || [])
      setTotal(data.total ?? 0)
    } catch (error) {
      console.error('获取文献失败:', error)
      setError(error.message || '获取文献失败，请稍后重试')
      setArticles([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.literatureStream}>
      <header className={styles.pageHeader}>
        <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>文献上新</h1>
        <TypewriterSubtitle
          text={[
            "运动科学8大子学科，4种文献类型，每日更新！",
            "目前收录PubMed2020年以来的全部运动科学文献！",
            "20年代的运动科学家都在干啥？",
          ]}
          active={titleVisible}
        />
      </header>

      <div className={styles.filtersCard}>
        <div className={styles.filterGroup}>
          <label>学科分类</label>
          <select
            value={filters.category}
            onChange={(e) => { setPage(1); setFilters({ ...filters, category: e.target.value }) }}
          >
            <option value="">全部分类</option>
            {categories.map((c) => (
              <option key={c.category_key} value={c.category_key}>
                {c.display_name} ({c.doc_count}篇)
              </option>
            ))}
          </select>
        </div>
        
        <div className={styles.filterGroup}>
          <label>文献类型</label>
          <select 
            value={filters.lit_type}
            onChange={(e) => { setPage(1); setFilters({...filters, lit_type: e.target.value}) }}
          >
            <option value="">全部类型</option>
            <option value="meta_analysis">Meta分析 & 系统综述</option>
            <option value="original">原创研究（全部）</option>
            <option value="original_human">　├─ 人体/理论研究</option>
            <option value="original_animal">　└─ 动物/细胞研究</option>
            <option value="review">叙述性综述</option>
            <option value="guideline">指南 & 共识</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label>时间窗口</label>
          <div className={styles.inlineRow}>
            <select 
              value={filters.window}
              onChange={(e) => { setPage(1); setFilters({...filters, window: e.target.value}) }}
            >
              <option value="today">今日上新</option>
              <option value="7d">最近7天</option>
              <option value="14d">最近14天</option>
              <option value="30d">最近30天</option>
              <option value="90d">最近90天</option>
              <option value="180d">最近180天</option>
              <option value="365d">最近1年</option>
              <option value="730d">最近2年</option>
              <option value="2020-01-01">自2020年起</option>
              <option value="2021-01-01">自2021年起</option>
              <option value="2022-01-01">自2022年起</option>
              <option value="2023-01-01">自2023年起</option>
              <option value="2024-01-01">自2024年起</option>
            </select>
            <button
              type="button"
              className={`${styles.toggleBtn} ${filters.topJournals ? styles.active : ''}`}
              onClick={() => { setPage(1); setFilters({ ...filters, topJournals: !filters.topJournals }) }}
              title="仅显示5本顶刊"
            >
              仅5本顶刊
            </button>
            <button
              type="button"
              className={`${styles.toggleBtn} ${filters.filterQuality ? styles.active : ''}`}
              onClick={() => { setPage(1); setFilters({ ...filters, filterQuality: !filters.filterQuality }) }}
              title="过滤四区期刊"
            >
              过滤四区
            </button>
            <button
              type="button"
              className={`${styles.toggleBtn} ${filters.onlyZone1 ? styles.active : ''}`}
              onClick={() => { setPage(1); setFilters({ ...filters, onlyZone1: !filters.onlyZone1 }) }}
              title="仅限中科院一区期刊"
            >
              仅限一区
            </button>
          </div>
        </div>

        <div className={`${styles.filterGroup} ${styles.filterGroupSearch}`}>
          <label>关键词搜索</label>
          <div className={styles.searchRow}>
            <input 
              type="text"
              placeholder="输入关键词..."
              value={filters.keywords}
              onChange={(e) => setFilters({...filters, keywords: e.target.value})}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  setPage(1)
                  fetchArticles()
                }
              }}
            />
            <select
              value={filters.searchScope}
              onChange={(e) => setFilters({ ...filters, searchScope: e.target.value })}
            >
              <option value="tiab">标题+摘要</option>
              <option value="ti">仅标题</option>
            </select>
            <div className={styles.filterActions}>
              <button onClick={() => { setPage(1); fetchArticles(); }}>
                搜索
              </button>
              <button
                className={styles.secondary}
                onClick={() => {
                  setPage(1)
                  setFilters({
                    category: '',
                    lit_type: '',
                    window: '30d',
                    keywords: '',
                    journal_issn: '',
                    searchScope: 'tiab',
                    topJournals: false,
                    filterQuality: false,
                    onlyZone1: false,
                    zones: []
                  })
                }}
              >
                重置
              </button>
              <div className={styles.zoneMultiFilter}>
                <span className={styles.zoneLabel}>分区:</span>
                {['1', '2', '3', '4'].map((z) => {
                  const active = filters.zones.includes(z)
                  return (
                    <button
                      key={z}
                      type="button"
                      className={`${styles.toggleBtn} ${active ? styles.active : ''}`}
                      onClick={() => {
                        const has = filters.zones.includes(z)
                        const next = has
                          ? filters.zones.filter((v) => v !== z)
                          : [...filters.zones, z]
                        setPage(1)
                        setFilters({ ...filters, zones: next })
                      }}
                    >
                      {z}区
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      {loading ? (
        <LoadingSpinner type="skeleton" count={5} />
      ) : error ? (
        <div className={styles.errorMessage}>
          <span className={styles.errorIcon}>⚠️</span>
          <p>{error}</p>
          <button onClick={fetchArticles} className={styles.retryButton}>重试</button>
        </div>
      ) : articles.length === 0 ? (
        <div className={styles.emptyState}>
          <p>暂无数据</p>
        </div>
      ) : (
        <>
          <div className={styles.articlesList}>
            {articles.map((article, index) => (
              <ArticleItem 
                key={article.pmid || index} 
                article={article} 
                index={index}
              />
            ))}
          </div>

          <Pagination
            currentPage={page}
            totalPages={Math.ceil(total / 20)}
            totalItems={total}
            perPage={20}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  )
}

export default LiteratureStream
