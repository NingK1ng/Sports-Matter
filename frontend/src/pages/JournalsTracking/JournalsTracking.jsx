import { useState, useEffect } from 'react'
import { journalsAPI } from '../../services/api'
import LoadingSpinner from '../../components/LoadingSpinner'
import Pagination from '../../components/Pagination'
import TypewriterSubtitle from '../../components/TypewriterSubtitle'
import JournalArticleItem from './JournalArticleItem'
import styles from './JournalsTracking.module.css'

function JournalsTracking() {
  const [category, setCategory] = useState('sports_science')
  const [articles, setArticles] = useState([])
  const [journals, setJournals] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({
    keywords: '',
    searchScope: 'tiab',
    timeWindow: '30d',
    issn: [],
    sortBy: 'date',
    sportsOnly: false
  })
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [titleVisible, setTitleVisible] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setTitleVisible(true), 300)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    loadJournals()
  }, [category])

  useEffect(() => {
    // 防抖：关键词输入时延迟300ms再请求，其他筛选立即触发
    const debounceTimeout = filters.keywords ? setTimeout(() => {
      loadArticles()
    }, 300) : null

    if (!filters.keywords) {
      loadArticles()
    }

    return () => {
      if (debounceTimeout) clearTimeout(debounceTimeout)
    }
  }, [category, filters, page])

  const loadJournals = async () => {
    try {
      const data = await journalsAPI.fetchJournalsList(category)
      setJournals(data || [])
    } catch (error) {
      console.error('加载期刊失败:', error)
    }
  }

  const loadArticles = async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {
        category,
        page,
        per_page: 20,
        sort_by: filters.sortBy
      }

      // 时间窗口转换
      if (filters.timeWindow) {
        // 统一 until = 今天（按发表日期口径）
        const today = new Date().toISOString().split('T')[0]
        params.until = today

        // “今日上新”= 今日更新（含入库与字段更新）
        if (filters.timeWindow === 'updated_today') {
          params.window = 'updated_today'
          delete params.until
        } else if (filters.timeWindow.endsWith('d')) {
          const days = parseInt(filters.timeWindow)
          const sinceDate = new Date()
          sinceDate.setDate(sinceDate.getDate() - days)
          params.since = sinceDate.toISOString().split('T')[0]
        } else {
          params.since = filters.timeWindow
        }
      }

      // 关键词
      if (filters.keywords) {
        params.keywords = filters.keywords
        params.search_scope = filters.searchScope
      }

      // 期刊筛选
      if (filters.issn.length > 0) {
        params.issn = filters.issn.join(',')
      }

      // CNS：运动相关过滤（依赖后端预计算标注）
      if (category === 'cns' && filters.sportsOnly) {
        params.sports_only = 'true'
      }

      const data = await journalsAPI.fetchJournalArticles(params)
      setArticles(data.items || [])
      setTotalPages(data.pages || 1)
      setTotal(data.total || 0)
    } catch (error) {
      console.error('加载文章失败:', error)
      setError(error.message || '加载文章失败，请稍后重试')
      setArticles([])
    } finally {
      setLoading(false)
    }
  }

  const handleCategoryChange = (newCategory) => {
    setCategory(newCategory)
    setPage(1)
    setFilters(prev => ({ ...prev, issn: [] })) // 清除期刊筛选
  }

  const handleJournalToggle = (issn) => {
    setFilters(prev => ({
      ...prev,
      issn: prev.issn.includes(issn)
        ? prev.issn.filter(i => i !== issn)
        : [...prev.issn, issn]
    }))
    setPage(1)
  }

  return (
    <div className={styles.journalsTracking}>
      <header className={styles.pageHeader}>
        <h1 className={`${styles.pageTitle} ${titleVisible ? styles.fadeIn : ''}`}>顶刊动向</h1>
        <TypewriterSubtitle
          text={[
            "时刻监视爬取运动科学顶刊及CNS顶刊文献！",
            "目前收录各期刊官网2020年以来的全部文献，开启您的20年代探险之旅！",
          ]}
          active={titleVisible}
        />
      </header>

      {/* 分类Tab */}
      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${category === 'sports_science' ? styles.active : ''}`}
          onClick={() => handleCategoryChange('sports_science')}
        >
          运动科学期刊
        </button>
        <button
          className={`${styles.tab} ${category === 'cns' ? styles.active : ''}`}
          onClick={() => handleCategoryChange('cns')}
        >
          CNS期刊
        </button>
      </div>

      {/* 筛选器 */}
      <div className={styles.filtersCard}>
        {/* 关键词搜索 */}
        <div className={styles.filterGroup}>
          <label>关键词搜索</label>
          <div className={styles.searchRow}>
            <input
              type="text"
              placeholder="输入关键词..."
              value={filters.keywords}
              onChange={(e) => setFilters({ ...filters, keywords: e.target.value })}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  setPage(1)
                  loadArticles()
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
          </div>
        </div>

        {/* 期刊筛选 */}
        <div className={styles.filterGroup}>
          <label>期刊筛选 ({filters.issn.length > 0 && `已选${filters.issn.length}个`})</label>
          <div className={styles.checkboxGroup}>
            {journals.length === 0 ? (
              <span className={styles.emptyText}>暂无期刊数据</span>
            ) : (
              journals.map(journal => (
                <label key={journal.issn_l}>
                  <input
                    type="checkbox"
                    checked={filters.issn.includes(journal.issn_l)}
                    onChange={() => handleJournalToggle(journal.issn_l)}
                  />
                  {journal.display_name}
                </label>
              ))
            )}
          </div>
        </div>

        {/* 时间窗口 */}
        <div className={styles.filterGroup}>
          <label>时间窗口</label>
          <select
          value={filters.timeWindow}
          onChange={(e) => {
            setFilters({ ...filters, timeWindow: e.target.value })
            setPage(1)
          }}
        >
          <option value="updated_today">今日上新</option>
          <option value="7d">过去7天</option>
          <option value="30d">过去30天</option>
            <option value="180d">过去半年</option>
            <option value="365d">过去1年</option>
            <option value="2020-01-01">2020年至今</option>
          </select>
        </div>

        {/* CNS：运动相关过滤 */}
        {category === 'cns' && (
          <div className={styles.filterGroup}>
            <button
              type="button"
              className={`${styles.sportsToggleBtn} ${
                filters.sportsOnly ? styles.sportsToggleBtnOn : styles.sportsToggleBtnOff
              }`}
              aria-pressed={!!filters.sportsOnly}
              onClick={() => {
                setFilters({ ...filters, sportsOnly: !filters.sportsOnly })
                setPage(1)
              }}
            >
              <span className={styles.sportsToggleLeft}>
                <img
                  src="/images/9bae4150acbd208.png"
                  alt=""
                  className={styles.sportsToggleIcon}
                  draggable="false"
                />
                <span>运动相关</span>
              </span>
              <span className={styles.sportsToggleState}>{filters.sportsOnly ? '开' : '关'}</span>
            </button>
          </div>
        )}

        {/* 排序方式 */}
        <div className={styles.filterGroup}>
          <label>排序方式</label>
          <select
            value={filters.sortBy}
            onChange={(e) => {
              setFilters({ ...filters, sortBy: e.target.value })
              setPage(1)
            }}
          >
            <option value="date">最新发表</option>
            <option value="citations">被引次数</option>
            <option value="relevance">相关度</option>
          </select>
        </div>

        <div className={styles.filterActions}>
          <button onClick={() => { setPage(1); loadArticles(); }}>
            搜索
          </button>
          <button
            className={styles.secondary}
            onClick={() => {
              setPage(1)
              setFilters({
                keywords: '',
                searchScope: 'tiab',
                timeWindow: '30d',
                issn: [],
                sortBy: 'date',
                sportsOnly: false
              })
            }}
          >
            重置
          </button>
        </div>
      </div>

      {/* 文章列表 */}
      {loading ? (
        <LoadingSpinner type="skeleton" count={5} />
      ) : error ? (
        <div className={styles.errorMessage}>
          <span className={styles.errorIcon}>⚠️</span>
          <p>{error}</p>
          <button onClick={loadArticles} className={styles.retryButton}>重试</button>
        </div>
      ) : articles.length === 0 ? (
        <div className={styles.emptyState}>
          <p>暂无数据</p>
        </div>
      ) : (
        <>
          <div className={styles.articlesList}>
            {articles.map((article, index) => (
              <JournalArticleItem
                key={article.doi || article.pmid || index}
                article={article}
                index={index}
              />
            ))}
          </div>

          <Pagination
            currentPage={page}
            totalPages={totalPages}
            totalItems={total}
            perPage={20}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  )
}

export default JournalsTracking
